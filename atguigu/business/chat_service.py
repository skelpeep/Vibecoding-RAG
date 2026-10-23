"""Short transactions, persistent session leases, and fail-closed history context."""
from datetime import timedelta
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from atguigu.business import models as m
from atguigu.business.authorization import authorized_units, owned_session
from atguigu.business.database import get_engine
from atguigu.business.security import load_principal
from atguigu.config.config import RuntimeConfig

TERMINAL_STATUSES = {"completed", "restricted", "no_match", "low_confidence", "error", "cancelled"}
# A bounded whole request with renewed leases permits recovery after a dead process.
LEASE_SECONDS = 30
REQUEST_TIMEOUT_SECONDS = max(30, min(600, RuntimeConfig.model_timeout * 5))


def session_factory():
    return Session(get_engine(), expire_on_commit=False)


def fresh_principal(db, user_id, token_version=None):
    user = db.get(m.User, user_id, populate_existing=True)
    if not user or user.status != "active" or (token_version is not None and user.token_version != token_version):
        raise HTTPException(401, "请登录或重新登录")
    principal = load_principal(db, user)
    if not {"ai:chat", "menu:ai"}.issubset(principal.permissions):
        raise HTTPException(403, "缺少问答操作权限")
    return principal


def valid_sources(db, principal, sources):
    """Validate each exact source tuple; missing provenance always closes the turn."""
    if not sources:
        return False
    units = {source.get("unit_id") for source in sources if isinstance(source, dict)}
    if None in units or not units or not units.issubset(authorized_units(db, principal, units)):
        return False
    for source in sources:
        if not isinstance(source, dict) or not all(source.get(key) for key in ("unit_id", "version_id", "chunk_id")):
            return False
        unit = db.get(m.KnowledgeUnit, source["unit_id"], populate_existing=True)
        chunk = db.get(m.KnowledgeChunk, source["chunk_id"], populate_existing=True)
        if not unit or unit.active_version_id != source["version_id"] or not chunk:
            return False
        if chunk.unit_id != source["unit_id"] or chunk.version_id != source["version_id"]:
            return False
    return True


def citation_sources(request_id, sources):
    allowed_keys = {"unit_id", "version_id", "chunk_id", "title", "position", "snippet", "score", "citation"}
    return [{**{key: value for key, value in source.items() if key in allowed_keys},
             "citation_url": f"/api/ai/chat/requests/{quote(request_id, safe='')}/citations/{quote(source['chunk_id'], safe='')}"}
            for source in sources]


def safe_turn(db, principal, turn, log):
    sources = turn.get("sources") or []
    dependencies = turn.get("authorization_dependencies") or []
    status = log.status if log else "error"
    # A completed answer without persisted provenance is never model context.
    trusted_completion = bool(log and log.details_json.get("history_persisted")
                              and log.status == "completed" and turn.get("status") == "completed"
                              and log.details_json.get("authorization_dependencies") == dependencies
                              and log.cited_sources_json == sources and (log.answer or "") == turn.get("answer", ""))
    redacted = bool(turn.get("redacted")) or (status == "completed" and (
        not trusted_completion or not valid_sources(db, principal, dependencies)))
    if log and log.details_json.get("reason") in {"history_finalize_failed", "database_finalize_failed", "permission_changed"}:
        redacted = True
    if sources and not valid_sources(db, principal, sources):
        redacted = True
    if dependencies and not valid_sources(db, principal, dependencies):
        redacted = True
    faq_metrics = (log.details_json or {}).get("metrics", {}) if log else {}
    if faq_metrics.get("faq_id"):
        from atguigu.business.faq_cache import valid_faq
        if not valid_faq(db, principal, faq_metrics["faq_id"], faq_metrics.get("faq_revision")):
            redacted = True
    if status != "completed" or not trusted_completion:
        # Do not expose a partially written cross-store result as a completion.
        content, safe_sources = "", []
    else:
        content, safe_sources = turn.get("answer", ""), sources
    if redacted:
        content, safe_sources = "", []
    details = log.details_json or {} if log else {}
    reason = details.get("reason") if log else "history_unproven"
    denied_count = details.get("metrics", {}).get("denied_count", 0)
    hint = None
    if redacted:
        hint = {"code": "permission_changed", "message": "来源访问范围已变化，请重新提问。"}
    elif denied_count and status in {"completed", "restricted"}:
        hint = {"code": "permission_required", "message": "部分相关知识需要访问权限，请联系管理员申请。"}
        if status == "completed" and not reason:
            reason = "partial_permission"
    return {"request_id": turn["_id"], "status": status, "reason": reason,
            "cache_status": log.cache_status if log else "unknown",
            "permission_hint": hint,
            "_external_sources": details.get("metrics", {}).get("external_sources", [])
                if not redacted and status in {"completed", "no_match", "low_confidence"}
                and details.get("history_persisted") else [],
            "created_at": turn.get("created_at"),
            "user": {"content": "" if redacted else turn.get("question", ""), "redacted": redacted},
            "assistant": {"content": content, "sources": citation_sources(turn["_id"], safe_sources), "redacted": redacted},
            "_authorization_dependencies": [] if redacted else dependencies}


def history_items(factory, store, user_id, token_version, session_id):
    turns = store.list(user_id, session_id)
    with factory() as db:
        principal = fresh_principal(db, user_id, token_version)
        owned_session(db, session_id, principal)
        logs = {row.id: row for row in db.scalars(select(m.QAAccessLog).where(
            m.QAAccessLog.session_id == session_id, m.QAAccessLog.user_id == user_id))}
        return [safe_turn(db, principal, turn, logs.get(turn["_id"])) for turn in turns]


def model_history(factory, store, user_id, token_version, session_id):
    result = []
    for item in history_items(factory, store, user_id, token_version, session_id):
        if item["status"] != "completed" or item["assistant"]["redacted"]:
            continue
        result.extend([{"role": "user", "content": item["user"]["content"], "sources": item["_authorization_dependencies"]},
                       {"role": "assistant", "content": item["assistant"]["content"], "sources": item["_authorization_dependencies"]}])
    return result[-20:]


def reserve(factory, store, user_id, token_version, question, session_id=None):
    """CAS reservation survives restarts; acceptance requires both stores to acknowledge."""
    request_id = m.new_id()
    now = m.utcnow()
    with factory() as db:
        principal = fresh_principal(db, user_id, token_version)
        if session_id:
            session = owned_session(db, session_id, principal)
        else:
            session = m.ChatSession(owner_id=user_id, title="新会话")
            db.add(session)
            db.flush()
            session_id = session.id
        previous = session.active_request_id
        claimed = db.execute(update(m.ChatSession).where(
            m.ChatSession.id == session_id, m.ChatSession.owner_id == user_id,
            m.ChatSession.status == "active", or_(m.ChatSession.active_request_id.is_(None),
                                                   m.ChatSession.lease_until.is_(None), m.ChatSession.lease_until <= now)
        ).values(active_request_id=request_id, lease_until=now + timedelta(seconds=LEASE_SECONDS), updated_at=now))
        if claimed.rowcount != 1:
            raise HTTPException(409, "此会话已有正在处理的问答")
        if previous:
            abandoned = db.get(m.QAAccessLog, previous)
            if abandoned and abandoned.status == "processing":
                abandoned.status, abandoned.finished_at = "cancelled", now
                abandoned.answer = None
                abandoned.response_time_ms = max(0, int((now - abandoned.created_at).total_seconds() * 1000))
                abandoned.details_json = {**(abandoned.details_json or {}), "reason": "lease_expired", "history_persisted": False}
        db.add(m.QAAccessLog(id=request_id, session_id=session_id, user_id=user_id, question=question,
                            cache_status="pending", details_json={"history_persisted": False}))
        db.commit()
    try:
        store.prepare()
        store.create({"_id": request_id, "owner_id": user_id, "session_id": session_id,
                      "created_at": now, "question": question, "answer": "", "sources": [],
                      "status": "processing", "rewritten_question": ""})
    except Exception:
        finalize(factory, store, user_id, session_id, request_id, status="error",
                 reason="history_preflight_failed", elapsed_ms=0, write_history=False)
        raise HTTPException(503, "对话历史存储暂不可用，请稍后重试") from None
    return session_id, request_id


def check_request(factory, user_id, token_version, session_id, request_id, sources=None, renew=False):
    with factory() as db:
        principal = fresh_principal(db, user_id, token_version)
        session = owned_session(db, session_id, principal)
        log = db.get(m.QAAccessLog, request_id, populate_existing=True)
        if not log or log.user_id != user_id or log.session_id != session_id or log.status != "processing":
            raise HTTPException(409, "问答已结束")
        if log.cancel_requested or session.active_request_id != request_id:
            raise HTTPException(409, "问答已取消")
        if sources and not valid_sources(db, principal, sources):
            raise HTTPException(403, "知识授权或当前版本已变化")
        if renew:
            claimed = db.execute(update(m.ChatSession).where(m.ChatSession.id == session_id,
                m.ChatSession.owner_id == user_id, m.ChatSession.status == "active",
                m.ChatSession.active_request_id == request_id,
                m.ChatSession.lease_until > m.utcnow()).values(
                    lease_until=m.utcnow() + timedelta(seconds=LEASE_SECONDS)))
            if claimed.rowcount != 1:
                raise HTTPException(409, "问答租约已结束")
            db.commit()


def finalize(factory, store, user_id, session_id, request_id, *, status, answer="", sources=None,
             metrics=None, usage=None, rewritten_question="", reason=None, elapsed_ms=0,
             first_token_ms=None, write_history=True, token_version=None):
    """Mongo completion first, MySQL authoritative state last. Never claim both on failure."""
    if status not in TERMINAL_STATUSES:
        status = "error"
    sources, metrics, usage = sources or [], metrics or {}, usage or {}
    dependencies = metrics.get("authorization_dependencies") or metrics.get("context_sources") or sources
    if status in {"cancelled", "error", "restricted"}:
        answer = ""
        sources = []
    history_ok = False
    now = m.utcnow()
    # Fence old producers before touching Mongo. MySQL remains authoritative if
    # the lease expires between this check and the final commit below.
    try:
        with factory() as db:
            log = db.get(m.QAAccessLog, request_id)
            session = db.get(m.ChatSession, session_id)
            if not log or log.user_id != user_id or log.session_id != session_id:
                raise RuntimeError("Owned request missing")
            if log.status != "processing":
                return {"status": log.status, "persisted": bool(log.details_json.get("history_persisted")),
                        "reason": log.details_json.get("reason")}
            fenced = not session or session.active_request_id != request_id or not session.lease_until or session.lease_until <= now
            if fenced:
                status, answer, sources, reason, write_history = "cancelled", "", [], "lease_expired", False
            elif log.cancel_requested or session.status != "active":
                status, answer, sources, reason = "cancelled", "", [], "cancel_requested"
            elif status == "completed":
                try:
                    principal = fresh_principal(db, user_id, token_version)
                    if not valid_sources(db, principal, dependencies):
                        raise HTTPException(403, "授权已变化")
                except HTTPException:
                    status, answer, sources, reason = "restricted", "", [], "permission_changed"
    except Exception:
        return {"status": "error", "persisted": False, "reason": "database_finalize_failed"}
    if write_history:
        try:
            store.finish(user_id, session_id, request_id, {"answer": answer, "sources": sources,
                "authorization_dependencies": dependencies,
                "rewritten_question": rewritten_question, "status": status, "finished_at": now,
                "redacted": status == "restricted" and reason in {"permission_changed", "identity_changed", "operation_revoked", "session_unavailable"}})
            history_ok = True
        except Exception:
            status, answer, sources, reason = "error", "", [], "history_finalize_failed"
    database_ok = False
    try:
        with factory() as db:
            # The reservation path locks session before old log; use the same
            # lock order during finalization to avoid a lease-recovery deadlock.
            session = db.scalar(select(m.ChatSession).where(m.ChatSession.id == session_id).with_for_update())
            log = db.scalar(select(m.QAAccessLog).where(m.QAAccessLog.id == request_id).with_for_update())
            if not log or log.user_id != user_id or log.session_id != session_id:
                raise RuntimeError("Owned request missing")
            if log.status != "processing":
                return {"status": log.status, "persisted": bool(log.details_json.get("history_persisted")),
                        "reason": log.details_json.get("reason")}
            if not session or session.active_request_id != request_id or not session.lease_until or session.lease_until <= m.utcnow():
                status, answer, sources, reason, history_ok = "cancelled", "", [], "lease_expired", False
            elif log.cancel_requested or session.status != "active":
                status, answer, sources, reason, history_ok = "cancelled", "", [], "cancel_requested", False
            elif status == "completed":
                try:
                    principal = fresh_principal(db, user_id, token_version)
                    if not valid_sources(db, principal, dependencies):
                        raise HTTPException(403, "授权已变化")
                except HTTPException:
                    status, answer, sources, reason, history_ok = "restricted", "", [], "permission_changed", False
            log.status, log.answer, log.finished_at = status, answer or None, now
            log.recalled_unit_ids_json = list(metrics.get("recalled_unit_ids", []))
            log.authorized_unit_ids_json = list(metrics.get("authorized_unit_ids", []))
            log.unauthorized_unit_ids_json = list(metrics.get("unauthorized_unit_ids", []))
            log.cited_sources_json = sources
            log.model_usage_json = usage
            log.cache_status = metrics.get("cache_status", "miss")
            if status == "completed" and metrics.get("faq_id"):
                from atguigu.business.faq_cache import valid_faq
                principal = fresh_principal(db, user_id, token_version)
                if not valid_faq(db, principal, metrics["faq_id"], metrics.get("faq_revision")):
                    log.status, log.answer, log.cited_sources_json = "restricted", None, []
                    status, reason, history_ok = "restricted", "faq_changed", False
                else:
                    db.execute(update(m.FAQ).where(m.FAQ.id == metrics["faq_id"]).values(hit_count=m.FAQ.hit_count + 1))
            def usage_entries(value):
                if isinstance(value, dict):
                    if "known" in value or any(key in value for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
                        return [value]
                    return [entry for child in value.values() for entry in usage_entries(child)]
                if isinstance(value, list):
                    return [entry for child in value for entry in usage_entries(child)]
                return []
            known = usage_entries(usage)
            for column in ("prompt_tokens", "completion_tokens", "total_tokens"):
                values = [value[column] for value in known if isinstance(value.get(column), int)]
                setattr(log, column, sum(values) if values else None)
            log.response_time_ms, log.first_token_ms = int(elapsed_ms), first_token_ms
            all_known = bool(known) and all(entry.get("known") is True for entry in known)
            any_known = any(entry.get("known") is True for entry in known)
            log.details_json = {"reason": reason, "history_persisted": history_ok, "metrics": metrics,
                                "usage_completeness": "complete" if all_known else ("partial" if any_known else "unknown"),
                                "authorization_dependencies": dependencies,
                                "rewritten_question": rewritten_question, "cache_implemented": True}
            db.execute(update(m.ChatSession).where(m.ChatSession.id == session_id,
                m.ChatSession.owner_id == user_id, m.ChatSession.active_request_id == request_id
            ).values(active_request_id=None, lease_until=None, updated_at=now))
            db.commit()
            database_ok = True
    except Exception:
        status, reason = "error", "database_finalize_failed"
    return {"status": status, "persisted": history_ok and database_ok, "reason": reason}
