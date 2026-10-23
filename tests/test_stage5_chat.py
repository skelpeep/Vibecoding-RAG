"""Owned SSE/lease/history safety using isolated SQLite + explicitly fake Mongo/model.

Real MySQL/Mongo/provider acceptance is exercised by verify_stage5_http.py.
"""
import asyncio
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from atguigu.business import chat_api as api, chat_service as service, models as m
from atguigu.business.security import issue_token
from atguigu.business.catalog import PERMISSIONS, ORDINARY, SYSTEM_ADMIN, KNOWLEDGE_ADMIN
from atguigu.business.database import get_db, make_engine
from atguigu.config.config import BusinessConfig
from atguigu.web.api.platform_service import app


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """Committed per-test SQLite DB permits independent async worker connections."""
    monkeypatch.setattr(BusinessConfig, "jwt_secret", "test-only-" + "randomness" * 5)
    engine = make_engine("sqlite:///" + str(tmp_path / "chat.db"))
    m.Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    db.add_all(m.Permission(**permission) for permission in PERMISSIONS)
    db.flush()
    roles, users = {}, {}
    for name, codes in (("employee", ORDINARY), ("admin", SYSTEM_ADMIN), ("kb", KNOWLEDGE_ADMIN), ("noop", set())):
        role = m.Role(role_name=name, role_code=name)
        db.add(role)
        db.flush()
        roles[name] = role
        db.add_all(m.RolePermission(role_id=role.id, permission_code=code,
            permission_type="menu" if code.startswith("menu:") else "operation") for code in codes)
    for name in ("alice", "bob", "admin", "kb", "noop"):
        user = m.User(username=name, display_name=name, password_hash="unused-hash")
        db.add(user)
        db.flush()
        users[name] = user
        db.add(m.UserRole(user_id=user.id, role_id=roles[name if name in roles else "employee"].id))
    db.commit()

    def dependency():
        with Session(engine, expire_on_commit=False) as request_db:
            try:
                yield request_db
                request_db.commit()
            except Exception:
                request_db.rollback()
                raise

    app.dependency_overrides[get_db] = dependency
    client = TestClient(app)
    tokens = {name: issue_token(user) for name, user in users.items()}

    def call(method, path, name="alice", **kwargs):
        return client.request(method, path, headers={"Authorization": "Bearer " + tokens[name]}, **kwargs)

    def unit(grants=()):
        row = m.KnowledgeUnit(unit_code=uuid4().hex, title="来源", creator_id=users["kb"].id, status="published")
        db.add(row)
        db.flush()
        version = m.KnowledgeVersion(unit_id=row.id, creator_id=users["kb"].id, version_number=1, status="ready")
        db.add(version)
        db.flush()
        row.active_version_id = version.id
        db.add_all(m.UnitPermission(unit_id=row.id, target_type=kind, target_id=target) for kind, target in grants)
        db.commit()
        return row

    yield SimpleNamespace(db=db, engine=engine, client=client, call=call, users=users, roles=roles, unit=unit)
    client.close()
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


class MemoryHistory:
    def __init__(self):
        self.turns = {}
        self.fail_prepare = False
        self.fail_finish = False

    def prepare(self):
        if self.fail_prepare:
            raise RuntimeError("private-api-key-do-not-echo")

    def create(self, turn):
        self.turns[turn["_id"]] = deepcopy(turn)

    def finish(self, owner_id, session_id, request_id, values):
        if self.fail_finish:
            raise RuntimeError("private-api-key-do-not-echo")
        item = self.turns[request_id]
        assert item["owner_id"] == owner_id and item["session_id"] == session_id
        item.update(deepcopy(values))

    def list(self, owner_id, session_id, limit=100):
        return deepcopy([item for item in self.turns.values()
                         if item["owner_id"] == owner_id and item["session_id"] == session_id][-limit:])

    def delete(self, owner_id, session_id):
        self.turns = {key: item for key, item in self.turns.items()
                      if item["owner_id"] != owner_id or item["session_id"] != session_id}


@pytest.fixture
def chat(ctx, monkeypatch):
    store = MemoryHistory()
    def factory():
        return Session(ctx.engine, expire_on_commit=False)

    monkeypatch.setattr(service, "session_factory", factory)
    monkeypatch.setattr(api, "get_history_store", lambda: store)
    return SimpleNamespace(store=store, factory=factory, owner=ctx.users["alice"].id,
                           token_version=ctx.users["alice"].token_version)


def source(ctx, unit):
    chunk = m.KnowledgeChunk(unit_id=unit.id, version_id=unit.active_version_id,
                            chunk_index=0, content="引用正文", position_json={"page": 1})
    ctx.db.add(chunk)
    ctx.db.commit()
    return {"unit_id": unit.id, "version_id": unit.active_version_id, "chunk_id": chunk.id,
            "title": "已发布来源", "snippet": "引用正文", "position": {"page": 1}, "citation": 1}


def make_completed(ctx, chat, citations, dependencies=None):
    sid, rid = service.reserve(chat.factory, chat.store, chat.owner, chat.token_version, "关联敏感提问")
    deps = citations if dependencies is None else dependencies
    payload = service.finalize(chat.factory, chat.store, chat.owner, sid, rid, status="completed",
        answer="敏感回答", sources=citations, metrics={"authorization_dependencies": deps,
            "recalled_unit_ids": list({x["unit_id"] for x in deps}),
            "authorized_unit_ids": list({x["unit_id"] for x in deps})},
        usage={"rewrite": [{"known": True, "prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}],
               "generate": [{"known": True, "prompt_tokens": 7, "completion_tokens": 11, "total_tokens": 18}]},
        rewritten_question="敏感改写", elapsed_ms=123, first_token_ms=22)
    assert payload["status"] == "completed" and payload["persisted"]
    return sid, rid


def test_session_and_request_ownership_body_principal_and_menu(ctx, chat):
    assert ctx.client.get("/api/ai/chat/sessions").status_code == 401
    assert ctx.call("GET", "/api/ai/chat/sessions", "noop").status_code == 403
    forged = ctx.call("POST", "/api/ai/chat/stream", json={"question": "hi", "user_id": ctx.users["bob"].id})
    assert forged.status_code == 422
    record = ctx.call("POST", "/api/ai/chat/sessions", json={"title": "会话"})
    assert record.status_code == 201
    sid = record.json()["id"]
    assert ctx.call("GET", f"/api/ai/chat/sessions/{sid}/messages", "bob").status_code == 404
    assert ctx.call("DELETE", f"/api/ai/chat/sessions/{sid}", "admin").status_code == 404
    assert ctx.call("POST", "/api/ai/chat/stream", "bob", json={"question": "hi", "session_id": sid}).status_code == 404
    sid, rid = service.reserve(chat.factory, chat.store, chat.owner, chat.token_version, "hi", sid)
    for suffix in ("", "/cancel"):
        method = "POST" if suffix else "GET"
        assert ctx.call(method, f"/api/ai/chat/requests/{rid}{suffix}", "bob").status_code == 404
    ctx.db.execute(delete(m.RolePermission).where(m.RolePermission.role_id == ctx.roles["employee"].id,
                                               m.RolePermission.permission_code == "menu:ai"))
    ctx.db.commit()
    assert ctx.call("GET", "/api/ai/chat/sessions").status_code == 403


def test_persistent_lease_conflict_recovery_and_old_producer_fence(ctx, chat):
    sid, old = service.reserve(chat.factory, chat.store, chat.owner, chat.token_version, "first")
    with pytest.raises(HTTPException) as exc:
        service.reserve(chat.factory, chat.store, chat.owner, chat.token_version, "conflict", sid)
    assert exc.value.status_code == 409
    with chat.factory() as db:
        session = db.get(m.ChatSession, sid)
        session.lease_until = m.utcnow() - timedelta(seconds=1)
        db.commit()
    _, new = service.reserve(chat.factory, chat.store, chat.owner, chat.token_version, "recovered", sid)
    with chat.factory() as db:
        assert db.get(m.QAAccessLog, old).status == "cancelled"
        assert db.get(m.ChatSession, sid).active_request_id == new
    before = deepcopy(chat.store.turns[old])
    late = service.finalize(chat.factory, chat.store, chat.owner, sid, old, status="completed", answer="late")
    assert late["status"] == "cancelled"
    assert chat.store.turns[old] == before
    with chat.factory() as db:
        assert db.get(m.ChatSession, sid).active_request_id == new


def test_uncited_dependency_revoke_redacts_whole_turn_and_context(ctx, chat):
    cited = source(ctx, ctx.unit([("user", chat.owner)]))
    influence = source(ctx, ctx.unit([("user", chat.owner)]))
    sid, rid = make_completed(ctx, chat, [cited], [cited, influence])
    assert len(service.model_history(chat.factory, chat.store, chat.owner, chat.token_version, sid)) == 2
    assert ctx.call("GET", f"/api/ai/chat/requests/{rid}/citations/{cited['chunk_id']}").status_code == 200
    ctx.db.execute(delete(m.UnitPermission).where(m.UnitPermission.unit_id == influence["unit_id"]))
    ctx.db.commit()
    history = ctx.call("GET", f"/api/ai/chat/sessions/{sid}/messages")
    assert history.status_code == 200
    turn = history.json()["items"][0]
    assert turn["user"] == {"content": "", "redacted": True}
    assert turn["assistant"] == {"content": "", "sources": [], "redacted": True}
    assert "敏感" not in history.text and "_authorization" not in history.text
    assert service.model_history(chat.factory, chat.store, chat.owner, chat.token_version, sid) == []
    assert ctx.call("GET", f"/api/ai/chat/requests/{rid}/citations/{cited['chunk_id']}").status_code == 404


def test_unproven_and_mismatched_crossstore_history_is_closed(ctx, chat):
    cited = source(ctx, ctx.unit([("user", chat.owner)]))
    sid, rid = make_completed(ctx, chat, [cited])
    with chat.factory() as db:
        log = db.get(m.QAAccessLog, rid)
        assert (log.prompt_tokens, log.completion_tokens, log.total_tokens) == (9, 14, 23)
        log.status = "error"
        db.commit()
    response = ctx.call("GET", f"/api/ai/chat/sessions/{sid}/messages")
    assert "敏感回答" not in response.text and "引用正文" not in response.text
    assert service.model_history(chat.factory, chat.store, chat.owner, chat.token_version, sid) == []


def test_mongo_preflight_and_terminal_failure_truthful_not_secret(ctx, chat):
    chat.store.fail_prepare = True
    with pytest.raises(HTTPException) as exc:
        service.reserve(chat.factory, chat.store, chat.owner, chat.token_version, "test")
    assert exc.value.status_code == 503 and "private-api-key" not in exc.value.detail
    with chat.factory() as db:
        log = db.scalar(select(m.QAAccessLog).where(m.QAAccessLog.user_id == chat.owner))
        assert log.status == "error" and not log.details_json["history_persisted"]
        assert db.get(m.ChatSession, log.session_id).active_request_id is None
    chat.store.fail_prepare = False
    sid, rid = service.reserve(chat.factory, chat.store, chat.owner, chat.token_version, "test")
    chat.store.fail_finish = True
    result = service.finalize(chat.factory, chat.store, chat.owner, sid, rid, status="no_match")
    assert result == {"status": "error", "persisted": False, "reason": "history_finalize_failed"}


class FakePipeline:
    def __init__(self, fail=False):
        self.fail = fail

    def snapshot(self):
        return {"metrics": {"recalled_unit_ids": [], "authorized_unit_ids": [], "unauthorized_unit_ids": []}, "usage": {}}

    async def run(self, **kwargs):
        await kwargs["on_progress"]({"stage": "retrieval"})
        if self.fail:
            raise RuntimeError("private-api-key-do-not-echo")
        return SimpleNamespace(status="no_match", answer="无知识依据", sources=[], permission_hint=None,
            metrics=self.snapshot()["metrics"], usage={}, rewritten_question=kwargs["question"])


@pytest.mark.parametrize("fail", [False, True])
def test_sse_sequences_and_all_errors_end(ctx, chat, monkeypatch, fail):
    monkeypatch.setattr(api, "get_pipeline", lambda factory: FakePipeline(fail))
    response = ctx.call("POST", "/api/ai/chat/stream", json={"question": "通用制度提问"})
    assert response.status_code == 200 and "text/event-stream" in response.headers["content-type"]
    import json
    events = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.splitlines()
        name = next(line[7:] for line in lines if line.startswith("event: "))
        payload = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        events.append((name, payload))
    assert [payload["seq"] for _, payload in events] == list(range(1, len(events) + 1))
    assert events[0][0] == "meta" and events[-1][0] == "end"
    assert events[-1][1]["status"] == ("error" if fail else "no_match")
    assert events[-1][1]["persisted"]
    assert "private-api-key" not in response.text
    if fail:
        assert events[-2][0] == "error"


def test_disconnect_after_meta_finalizes_cancelled(ctx, chat):
    sid, rid = service.reserve(chat.factory, chat.store, chat.owner, chat.token_version, "disconnect")

    class Disconnected:
        async def is_disconnected(self):
            return True

    async def consume():
        generator = api.chat_events(Disconnected(), chat.factory, chat.store, FakePipeline(), chat.owner,
                                    chat.token_version, sid, rid, "disconnect")
        assert "event: meta" in await anext(generator)
        with pytest.raises(StopAsyncIteration):
            await anext(generator)

    asyncio.run(consume())
    with chat.factory() as db:
        log = db.get(m.QAAccessLog, rid)
        assert log.status == "cancelled" and log.details_json["reason"] == "client_disconnected"
        assert db.get(m.ChatSession, sid).active_request_id is None


def test_history_external_metadata_rejects_unsafe_urls_and_revoked_dependencies(ctx, chat):
    cited = source(ctx, ctx.unit([("user", chat.owner)]))
    sid, rid = make_completed(ctx, chat, [cited])
    with chat.factory() as db:
        log = db.get(m.QAAccessLog, rid)
        details = deepcopy(log.details_json)
        details["metrics"]["external_sources"] = [
            {"title": "安全补充", "url": "https://example.com/policy", "snippet": "公开信息"},
            {"title": "恶意", "url": "javascript:alert(1)"},
            {"title": "本地", "url": "file:///private"}]
        log.details_json = details
        db.commit()
    response = ctx.call("GET", f"/api/ai/chat/sessions/{sid}/messages")
    sources = response.json()["items"][0]["external_sources"]
    assert len(sources) == 1 and sources[0]["source_type"] == "external"
    assert "javascript:" not in response.text and "file:///" not in response.text
    ctx.db.execute(delete(m.UnitPermission).where(m.UnitPermission.unit_id == cited["unit_id"]))
    ctx.db.commit()
    redacted = ctx.call("GET", f"/api/ai/chat/sessions/{sid}/messages").json()["items"][0]
    assert redacted["assistant"]["redacted"] and redacted["external_sources"] == []
