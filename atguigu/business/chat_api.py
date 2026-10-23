"""Authenticated, owned chat API and SSE transport with explicit terminal states."""
import asyncio
import json
import anyio
from time import monotonic
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update

from atguigu.business import chat_service as service, models as m
from atguigu.business.authorization import owned_session
from atguigu.business.chat_history import get_history_store
from atguigu.business.chat_schemas import ChatQuestion, SessionCreate
from atguigu.business.security import Current, Db, Principal

router = APIRouter(prefix="/api/ai/chat", tags=["鉴权问答"])


def require_chat(principal: Current):
    if not {"menu:ai", "ai:chat"}.issubset(principal.permissions):
        raise HTTPException(403, "缺少问答操作权限")
    return principal


Chat = Annotated[Principal, Depends(require_chat)]


def session_json(session):
    return {"id": session.id, "title": session.title, "status": session.status,
            "created_at": session.created_at, "updated_at": session.updated_at,
            "active_request_id": session.active_request_id}


@router.get("/sessions")
def sessions(db: Db, principal: Chat, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100)):
    conditions = (m.ChatSession.owner_id == principal.user.id, m.ChatSession.status == "active")
    total = db.scalar(select(func.count()).select_from(m.ChatSession).where(*conditions))
    rows = db.scalars(select(m.ChatSession).where(*conditions).order_by(m.ChatSession.updated_at.desc(),
        m.ChatSession.id).offset((page - 1) * page_size).limit(page_size))
    return {"items": [session_json(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/sessions", status_code=201)
def create_session(body: SessionCreate, db: Db, principal: Chat):
    row = m.ChatSession(owner_id=principal.user.id, title=body.title)
    db.add(row)
    db.flush()
    return session_json(row)


@router.get("/sessions/{session_id}/messages")
def messages(session_id: str, db: Db, principal: Chat, response: Response):
    owned_session(db, session_id, principal)
    response.headers["Cache-Control"] = "no-store"
    try:
        items = service.history_items(service.session_factory, get_history_store(), principal.user.id,
                                      principal.user.token_version, session_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "对话历史存储暂不可用") from None
    return {"session_id": session_id, "items": [
        {**{key: value for key, value in item.items() if not key.startswith("_")},
         "external_sources": public_external_sources(item.get("_external_sources", []))} for item in items]}


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, db: Db, principal: Chat):
    session = owned_session(db, session_id, principal)
    # First make it invisible and request cancellation; retained MySQL audit logs
    # deliberately prevent hard deletion of the ownership parent.
    if session.active_request_id:
        log = db.get(m.QAAccessLog, session.active_request_id)
        if log and log.user_id == principal.user.id:
            log.cancel_requested = True
    session.status = "deleted"
    db.commit()
    try:
        get_history_store().delete(principal.user.id, session_id)
    except Exception:
        raise HTTPException(503, "会话已关闭，历史清理暂未完成") from None


def owned_request(db, request_id, principal):
    log = db.get(m.QAAccessLog, request_id)
    if not log or log.user_id != principal.user.id:
        raise HTTPException(404, "资源不存在或不可访问")
    owned_session(db, log.session_id, principal)
    return log


@router.get("/requests/{request_id}")
def request_status(request_id: str, db: Db, principal: Chat, response: Response):
    log = owned_request(db, request_id, principal)
    response.headers["Cache-Control"] = "no-store"
    return {"request_id": log.id, "session_id": log.session_id, "status": log.status,
            "cancel_requested": log.cancel_requested, "created_at": log.created_at,
            "finished_at": log.finished_at, "persisted": bool(log.details_json.get("history_persisted")),
            "duration_ms": log.response_time_ms, "first_token_ms": log.first_token_ms,
            "cache_status": log.cache_status}


@router.post("/requests/{request_id}/cancel")
def cancel_request(request_id: str, db: Db, principal: Chat):
    log = owned_request(db, request_id, principal)
    if log.status == "processing":
        log.cancel_requested = True
    return {"request_id": log.id, "status": log.status, "cancel_requested": log.cancel_requested}


@router.get("/requests/{request_id}/citations/{chunk_id}")
def citation(request_id: str, chunk_id: str, db: Db, principal: Chat, response: Response):
    log = owned_request(db, request_id, principal)
    metrics = log.details_json.get("metrics", {})
    if metrics.get("faq_id"):
        from atguigu.business.faq_cache import valid_faq
        if not valid_faq(db, principal, metrics["faq_id"], metrics.get("faq_revision")):
            raise HTTPException(404, "FAQ 已变化，引用当前不可访问")
    if log.status != "completed" or not log.details_json.get("history_persisted") or not service.valid_sources(
            db, principal, log.details_json.get("authorization_dependencies", [])):
        raise HTTPException(404, "引用不存在或当前不可访问")
    source = next((source for source in log.cited_sources_json if source.get("chunk_id") == chunk_id), None)
    if not source:
        raise HTTPException(404, "引用不存在或当前不可访问")
    chunk = db.get(m.KnowledgeChunk, chunk_id)
    version = db.get(m.KnowledgeVersion, source["version_id"])
    title = (version.metadata_json or {}).get("title", "知识来源")
    response.headers["Cache-Control"] = "no-store"
    # No storage keys or attachment links; separate file routes enforce file RBAC.
    return {"unit_id": chunk.unit_id, "version_id": chunk.version_id, "chunk_id": chunk.id,
            "title": title, "content": chunk.content, "position": chunk.position_json}


def get_pipeline(factory):
    from atguigu.business.rag import RagPipeline
    from atguigu.business.faq_cache import CachedPipeline
    return CachedPipeline(factory, RagPipeline(session_factory=factory))


def public_external_sources(values):
    result = []
    for value in (values or [])[:8]:
        if not isinstance(value, dict):
            continue
        url = value.get("url", "")
        if not isinstance(url, str) or len(url) > 2048 or urlparse(url).scheme not in {"http", "https"}:
            continue
        result.append({"source_type": "external", "label": "联网补充来源",
                       "title": str(value.get("title", "外部网页"))[:200],
                       "snippet": str(value.get("snippet", ""))[:1200], "url": url})
    return result


async def chat_events(request, factory, store, pipeline, user_id, token_version, session_id, request_id, question):
    started = monotonic()
    queue = asyncio.Queue(maxsize=32)
    source_state = []
    first_token_ms = None
    seq = 0
    finalized = False
    final_payload = None
    producer = None

    def event(name, payload):
        nonlocal seq
        seq += 1
        data = {**payload, "seq": seq, "request_id": request_id, "session_id": session_id}
        return f"id: {request_id}:{seq}\nevent: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

    async def check(sources=None, renew=False):
        await asyncio.to_thread(service.check_request, factory, user_id, token_version,
                                session_id, request_id, sources, renew)
        snapshot = pipeline.snapshot() if hasattr(pipeline, "snapshot") else {}
        metrics = snapshot.get("metrics", {})
        if metrics.get("faq_id"):
            def check_faq():
                from atguigu.business.faq_cache import valid_faq
                with factory() as db:
                    principal = service.fresh_principal(db, user_id, token_version)
                    if not valid_faq(db, principal, metrics["faq_id"], metrics.get("faq_revision")):
                        raise HTTPException(403, "FAQ 已变化")
            await asyncio.to_thread(check_faq)

    async def on_sources(sources):
        await check(sources)
        source_state[:] = sources
        await queue.put(("sources", {"sources": service.citation_sources(request_id, sources)}))

    async def on_delta(text):
        nonlocal first_token_ms
        if not text:
            return
        snapshot = pipeline.snapshot() if hasattr(pipeline, "snapshot") else {}
        dependencies = snapshot.get("metrics", {}).get("authorization_dependencies") or source_state
        await check(dependencies)
        if first_token_ms is None:
            first_token_ms = int((monotonic() - started) * 1000)
        await queue.put(("delta", {"text": text}))

    async def on_progress(value):
        await check()
        # Only safe node/status metadata may enter the public stream.
        safe = {key: value[key] for key in ("stage", "status", "message") if isinstance(value, dict) and key in value}
        await queue.put(("progress", safe))
        if isinstance(value, dict) and value.get("external_sources"):
            await queue.put(("external_sources", {"sources": public_external_sources(value["external_sources"])}))

    async def history_loader():
        return await asyncio.to_thread(service.model_history, factory, store, user_id, token_version, session_id)

    async def run():
        result = await pipeline.run(user_id=user_id, token_version=token_version, session_id=session_id,
            question=question, history_loader=history_loader, on_delta=on_delta,
            on_progress=on_progress, on_sources=on_sources)
        return result

    async def finish(status, **kwargs):
        nonlocal finalized, final_payload
        # Pipeline retains per-request observations even when cancelled mid-call.
        snapshot = pipeline.snapshot() if hasattr(pipeline, "snapshot") else {}
        kwargs.setdefault("metrics", snapshot.get("metrics", {}))
        kwargs.setdefault("usage", snapshot.get("usage", {}))
        payload = await asyncio.to_thread(service.finalize, factory, store, user_id, session_id,
            request_id, status=status, elapsed_ms=int((monotonic() - started) * 1000),
            first_token_ms=first_token_ms, token_version=token_version, **kwargs)
        finalized = True
        final_payload = {**payload, "duration_ms": int((monotonic() - started) * 1000),
                         "first_token_ms": first_token_ms, "cache_status": kwargs.get("metrics", {}).get("cache_status", "miss"),
                         "usage": kwargs.get("usage") or {},
                         "external_sources": public_external_sources(kwargs.get("metrics", {}).get("external_sources", []))}
        return final_payload

    async def stop():
        if producer and not producer.done():
            producer.cancel()
            # Remote calls are async and close on cancellation; still impose an
            # upper bound when an adapter mishandles cancellation.
            done, _ = await asyncio.wait({producer}, timeout=1)
            if done:
                try:
                    producer.result()
                except BaseException:
                    pass

    try:
        yield event("meta", {"status": "processing", "protocol_version": 1, "cache_status": "pending"})
        producer = asyncio.create_task(run())
        last_heartbeat = monotonic()
        while True:
            if await request.is_disconnected():
                await stop()
                await finish("cancelled", sources=source_state, reason="client_disconnected")
                return
            if monotonic() - started > service.REQUEST_TIMEOUT_SECONDS:
                await stop()
                raise TimeoutError()
            try:
                await check(source_state, renew=True)
            except HTTPException as exc:
                await stop()
                if exc.status_code == 409:
                    payload = await finish("cancelled", sources=source_state, reason="cancel_requested")
                    yield event("permission", {"code": "cancelled", "message": "问答已停止", "clear_answer": True})
                else:
                    payload = await finish("restricted", sources=source_state, reason="permission_changed")
                    yield event("permission", {"code": "permission_changed", "message": "授权已变化，请重新提问", "clear_answer": True})
                yield event("end", payload)
                return
            if producer.done() and queue.empty():
                result = producer.result()
                status = result.status if result.status in service.TERMINAL_STATUSES else "error"
                hint = getattr(result, "permission_hint", None)
                if status == "restricted":
                    yield event("permission", {"code": (hint or {}).get("reason", "restricted"),
                        "message": (hint or {}).get("message", "部分知识尚未授权"), "clear_answer": True})
                elif hint:
                    yield event("permission", {"code": hint.get("reason", "partial_permission"),
                        "message": hint.get("message", "回答仅依据当前可访问知识"), "clear_answer": False})
                sources = getattr(result, "sources", [])
                # Revalidate immediately before storing/announcing final answer.
                if status == "completed":
                    await check(sources)
                    if not sources:
                        status = "error"
                    else:
                        yield event("sources", {"sources": service.citation_sources(request_id, sources), "final": True})
                payload = await finish(status, answer=result.answer, sources=sources,
                    metrics=getattr(result, "metrics", {}), usage=getattr(result, "usage", {}),
                    rewritten_question=getattr(result, "rewritten_question", ""),
                    reason="permission_changed" if (hint or {}).get("code") == "permission_changed" else (hint or {}).get("reason"))
                if payload["status"] == "restricted" and status != "restricted":
                    yield event("permission", {"code": "permission_changed", "message": "授权已变化，请重新提问", "clear_answer": True})
                if payload["status"] == "cancelled" and status != "cancelled":
                    yield event("permission", {"code": "cancelled", "message": "问答已停止", "clear_answer": True})
                if (not payload["persisted"] or payload["status"] == "error") and payload["status"] != "restricted":
                    yield event("error", {"code": payload.get("reason") or "rag_failed",
                        "message": "问答处理或持久化失败，请稍后重试", "clear_answer": True})
                yield event("end", payload)
                return
            try:
                name, payload = await asyncio.wait_for(queue.get(), timeout=0.2)
                await check(source_state)
                yield event(name, payload)
            except asyncio.TimeoutError:
                if monotonic() - last_heartbeat >= 5:
                    last_heartbeat = monotonic()
                    yield ": heartbeat\n\n"
    except asyncio.CancelledError:
        # StreamingResponse uses an AnyIO cancellation scope, so asyncio.shield
        # alone cannot protect cleanup from repeated scope cancellation.
        with anyio.CancelScope(shield=True):
            await stop()
            if not finalized:
                await finish("cancelled", sources=source_state, reason="client_disconnected")
        raise
    except HTTPException as exc:
        await stop()
        status = "cancelled" if exc.status_code == 409 else "restricted"
        payload = await finish(status, sources=source_state, reason="permission_changed" if status == "restricted" else "cancel_requested")
        yield event("permission", {"code": payload["reason"], "message": "问答已停止或授权已变化", "clear_answer": True})
        yield event("end", payload)
    except Exception:
        await stop()
        payload = await finish("error", sources=source_state, reason="request_failed")
        yield event("error", {"code": "request_failed", "message": "问答服务暂不可用，请稍后重试", "clear_answer": True})
        yield event("end", payload)
    finally:
        if not finalized:
            with anyio.CancelScope(shield=True):
                await stop()
                await finish("cancelled", sources=source_state, reason="client_disconnected")


@router.post("/stream")
def stream(body: ChatQuestion, request: Request, principal: Chat):
    factory, store = service.session_factory, get_history_store()
    session_id, request_id = service.reserve(factory, store, principal.user.id, principal.user.token_version,
                                              body.question, body.session_id)
    try:
        pipeline = get_pipeline(factory)
    except Exception:
        service.finalize(factory, store, principal.user.id, session_id, request_id,
                         status="error", reason="pipeline_unavailable")
        raise HTTPException(503, "问答服务暂不可用") from None
    return StreamingResponse(chat_events(request, factory, store, pipeline, principal.user.id,
        principal.user.token_version, session_id, request_id, body.question), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "X-Request-ID": request_id})
