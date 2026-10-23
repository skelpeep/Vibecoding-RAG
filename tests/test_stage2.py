"""Permission boundary suite; optionally runs inside rolled-back real MySQL transactions.

KB_TEST_MYSQL=1 selects the configured migrated MySQL database. Every case inserts
unique fixture records inside a transaction and rolls it back, including API commits.
No existing account, password, grant or business record is edited.
"""
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from atguigu.business import models as m
from atguigu.business.catalog import PERMISSIONS, SYSTEM_ADMIN, KNOWLEDGE_ADMIN, ORDINARY
from atguigu.business.database import get_db, get_engine, make_engine
from atguigu.business.security import hash_password, issue_token, legacy_data_closed
from atguigu.config.config import BusinessConfig
from atguigu.web.api.platform_service import app

PASSWORD = "Stage2-test-password-strong"
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    if os.getenv("KB_TEST_MYSQL") == "1":
        result = get_engine()
        with result.connect() as c:
            assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
    else:
        result = make_engine("sqlite:///" + str(tmp_path_factory.mktemp("stage2") / "tests.db"))
        m.Base.metadata.create_all(result)
    yield result
    if os.getenv("KB_TEST_MYSQL") != "1":
        result.dispose()


@pytest.fixture
def ctx(engine, monkeypatch):
    monkeypatch.setattr(BusinessConfig, "jwt_secret", "test-only-" + "randomness" * 5)
    prefix = "t" + uuid4().hex[:10]
    connection = engine.connect()
    transaction = connection.begin()
    # Python sqlite's legacy transaction mode needs an explicit BEGIN before SAVEPOINT.
    if engine.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN")
    db = Session(connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
    for p in PERMISSIONS:
        if not db.get(m.Permission, p["code"]):
            db.add(m.Permission(**p))
            db.flush()
    departments = {}
    for name, parent in [("tech", None), ("sales", None), ("dev", "tech")]:
        d = m.Department(code=prefix + name, name=name, parent_id=departments[parent].id if parent else None)
        db.add(d); db.flush(); departments[name] = d
    roles = {}
    for name, codes in [("admin", SYSTEM_ADMIN), ("kb", KNOWLEDGE_ADMIN), ("employee", ORDINARY),
                        ("engineer", set()), ("noop", set())]:
        role = m.Role(role_code=prefix + name, role_name=name)
        db.add(role); db.flush(); roles[name] = role
        db.add_all(m.RolePermission(role_id=role.id, permission_code=code,
                                   permission_type="menu" if code.startswith("menu:") else "operation") for code in codes)
        db.flush()
    users = {}
    for name, department, assigned in [("admin", "tech", ["admin"]), ("kb", "tech", ["kb"]),
                                        ("alice", "tech", ["employee", "engineer"]), ("bob", "sales", ["employee"]),
                                        ("carol", "dev", ["employee"]), ("noop", "sales", ["noop"])]:
        u = m.User(username=prefix + name, display_name=name, password_hash=PASSWORD_HASH,
                   department_id=departments[department].id)
        db.add(u); db.flush(); users[name] = u
        db.add_all(m.UserRole(user_id=u.id, role_id=roles[role].id) for role in assigned)
        db.flush()
    db.commit()

    def session_dependency():
        with Session(connection, expire_on_commit=False, join_transaction_mode="create_savepoint") as request_db:
            try:
                yield request_db
                request_db.commit()
            except Exception:
                request_db.rollback()
                raise
    app.dependency_overrides[get_db] = session_dependency
    client = TestClient(app)
    tokens = {name: issue_token(u) for name, u in users.items()}

    def headers(name="alice"):
        return {"Authorization": "Bearer " + tokens[name]}

    def call(method, path, name="alice", **kwargs):
        return client.request(method, path, headers=headers(name), **kwargs)

    def unit(grants=(), status="published", ready=True):
        record = m.KnowledgeUnit(unit_code=uuid4().hex, title="受限测试正文", creator_id=users["kb"].id,
                                 status=status, content="不得泄露")
        db.add(record); db.flush()
        version = m.KnowledgeVersion(unit_id=record.id, creator_id=users["kb"].id, version_number=1,
                                    content="受限版本正文", status="ready" if ready else "failed")
        db.add(version); db.flush()
        record.active_version_id = version.id
        db.add_all(m.UnitPermission(unit_id=record.id, target_type=kind, target_id=target) for kind, target in grants)
        db.commit()
        return record

    yield SimpleNamespace(db=db, client=client, users=users, roles=roles, departments=departments,
                          call=call, headers=headers, tokens=tokens, unit=unit, prefix=prefix,
                          dependency=session_dependency)
    client.close()
    app.dependency_overrides.clear()
    db.close()
    transaction.rollback()
    connection.close()


def check(ctx, ids, name="alice"):
    response = ctx.call("POST", "/api/knowledge/check-permissions", name, json={"unit_ids": ids})
    assert response.status_code == 200, response.text
    return response.json()


def test_login_identity_and_safe_profile(ctx):
    r = ctx.client.post("/api/auth/login", json={"username": ctx.users["alice"].username, "password": PASSWORD})
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["user_info"]["id"] == ctx.users["alice"].id
    assert "ai:chat" in payload["permissions"]
    assert "password_hash" not in r.text and "token_version" not in r.text
    assert ctx.call("GET", "/api/auth/me").status_code == 200
    r = ctx.call("PUT", "/api/auth/profile", json={"display_name": "新的显示名", "email": "alice@example.test"})
    assert r.status_code == 200 and r.json()["display_name"] == "新的显示名"
    assert ctx.call("PUT", "/api/auth/profile", json={"display_name": "x", "role_ids": [ctx.roles["admin"].id]}).status_code == 422
    assert ctx.client.post("/api/auth/login", json={"username": ctx.users["alice"].username, "password": "bad"}).status_code == 401
    r = ctx.client.post("/api/auth/login", json={"username": "INVALID", "password": "private-do-not-echo"})
    assert r.status_code == 422 and "private-do-not-echo" not in r.text


def test_anonymous_disabled_no_operation(ctx):
    assert ctx.client.get("/api/auth/me").status_code == 401
    assert ctx.client.post("/api/knowledge/check-permissions", json={"unit_ids": ["missing"]}).status_code == 401
    assert ctx.call("GET", "/api/org/users").status_code == 403
    assert ctx.call("POST", "/api/knowledge/check-permissions", "noop", json={"unit_ids": ["missing"]}).status_code == 403
    user_id = ctx.users["alice"].id
    assert ctx.call("POST", f"/api/org/users/{user_id}/status", "admin", json={"status": "disabled"}).status_code == 200
    assert ctx.call("GET", "/api/auth/me").status_code == 401
    assert ctx.client.post("/api/auth/login", json={"username": ctx.users["alice"].username, "password": PASSWORD}).status_code == 401
    assert ctx.call("POST", f"/api/org/users/{user_id}/status", "admin", json={"status": "active"}).status_code == 200
    assert ctx.call("GET", "/api/auth/me").status_code == 401  # Reactivation cannot revive old tokens.


@pytest.mark.parametrize("kind,target_name", [("global", None), ("department", "tech"), ("role", "engineer"), ("user", "alice")])
def test_each_grant_dimension(ctx, kind, target_name):
    target = {"global": "*", "department": ctx.departments["tech"].id,
              "role": ctx.roles["engineer"].id, "user": ctx.users["alice"].id}[kind]
    u = ctx.unit([(kind, target)])
    assert check(ctx, [u.id])["authorized_unit_ids"] == [u.id]
    expected = [u.id] if kind == "global" else []
    assert check(ctx, [u.id], "bob")["authorized_unit_ids"] == expected


def test_or_default_deny_no_department_inheritance_and_no_admin_bypass(ctx):
    mixed = ctx.unit([("department", ctx.departments["sales"].id), ("role", ctx.roles["engineer"].id)])
    empty = ctx.unit()
    tech = ctx.unit([("department", ctx.departments["tech"].id)])
    assert check(ctx, [mixed.id, empty.id, "missing"])["authorized_unit_ids"] == [mixed.id]
    assert check(ctx, [mixed.id], "bob")["authorized_unit_ids"] == [mixed.id]
    assert check(ctx, [tech.id], "carol")["unauthorized_unit_ids"] == [tech.id]
    assert check(ctx, [empty.id], "admin")["unauthorized_unit_ids"] == [empty.id]
    assert check(ctx, [empty.id], "kb")["unauthorized_unit_ids"] == [empty.id]  # Creator also denied.


@pytest.mark.parametrize("status,ready", [("draft", True), ("disabled", True), ("deleted", True), ("published", False)])
def test_non_published_or_unready_denied(ctx, status, ready):
    u = ctx.unit([("global", "*")], status=status, ready=ready)
    assert check(ctx, [u.id])["unauthorized_unit_ids"] == [u.id]


def test_grant_revocation_validation_and_event(ctx):
    u = ctx.unit([("user", ctx.users["alice"].id)])
    assert check(ctx, [u.id])["authorized_unit_ids"] == [u.id]
    path = f"/api/knowledge/units/{u.id}/permissions"
    assert ctx.call("POST", path, json={"grants": []}).status_code == 403
    assert ctx.call("POST", path, "kb", json={"grants": []}).status_code == 200
    assert check(ctx, [u.id])["authorized_unit_ids"] == []
    assert ctx.db.scalar(select(func.count()).select_from(m.OutboxEvent).where(m.OutboxEvent.aggregate_id == u.id)) == 1
    for grant in [{"target_type": "global", "target_id": ctx.users["alice"].id}, {"target_type": "role", "target_id": "missing"}]:
        assert ctx.call("POST", path, "kb", json={"grants": [grant]}).status_code == 422
    grant = {"target_type": "global", "target_id": "*"}
    assert ctx.call("POST", path, "kb", json={"grants": [grant, grant]}).status_code == 200
    assert ctx.call("GET", path, "kb").json()["grants"] == [grant]


def test_forged_identity_and_privileged_preview(ctx):
    u = ctx.unit([("user", ctx.users["bob"].id)])
    body = {"unit_ids": [u.id], "user_id": ctx.users["bob"].id}
    assert ctx.call("POST", "/api/knowledge/check-permissions", json=body).status_code == 422
    assert ctx.call("POST", "/api/knowledge/preview-permissions", json=body).status_code == 403
    assert ctx.call("POST", "/api/knowledge/preview-permissions", "admin", json=body).json()["authorized_unit_ids"] == [u.id]
    assert ctx.call("POST", "/api/knowledge/check-permissions?user_id=" + ctx.users["bob"].id,
                    json={"unit_ids": [u.id]}).json()["authorized_unit_ids"] == []
    assert "受限" not in str(check(ctx, [u.id]))
    assert ctx.call("POST", "/api/knowledge/check-permissions", json={"unit_ids": [u.id] * 501}).status_code == 422


def test_role_and_department_changes_affect_existing_token(ctx):
    u = ctx.unit([("role", ctx.roles["engineer"].id)])
    assert check(ctx, [u.id])["authorized_unit_ids"] == [u.id]
    user_id = ctx.users["alice"].id
    assert ctx.call("POST", f"/api/org/users/{user_id}/roles", "admin",
                    json={"role_ids": [ctx.roles["employee"].id]}).status_code == 200
    assert check(ctx, [u.id])["authorized_unit_ids"] == []
    department_unit = ctx.unit([("department", ctx.departments["tech"].id)])
    assert check(ctx, [department_unit.id])["authorized_unit_ids"] == [department_unit.id]
    assert ctx.call("PUT", f"/api/org/users/{user_id}", "admin", json={"display_name": "Alice", "department_id": ctx.departments["sales"].id}).status_code == 200
    assert check(ctx, [department_unit.id])["authorized_unit_ids"] == []
    assert ctx.call("POST", f"/api/org/roles/{ctx.roles['employee'].id}/permissions", "admin", json={"permission_codes": []}).status_code == 200
    assert ctx.call("POST", "/api/knowledge/check-permissions", json={"unit_ids": [u.id]}).status_code == 403
    assert ctx.call("GET", "/api/auth/menus").json() == {"items": []}


@pytest.mark.parametrize("mode", ["reset", "change", "logout"])
def test_password_and_logout_revoke_tokens(ctx, mode):
    user_id = ctx.users["alice"].id
    if mode == "reset":
        r = ctx.call("POST", f"/api/org/users/{user_id}/reset-password", "admin", json={"password": PASSWORD + "-new"})
    elif mode == "change":
        r = ctx.call("POST", "/api/auth/password", json={"current_password": PASSWORD, "new_password": PASSWORD + "-new"})
    else:
        r = ctx.call("POST", "/api/auth/logout")
    assert r.status_code == 200, r.text
    assert ctx.call("GET", "/api/auth/me").status_code == 401
    next_password = PASSWORD if mode == "logout" else PASSWORD + "-new"
    assert ctx.client.post("/api/auth/login", json={"username": ctx.users["alice"].username, "password": next_password}).status_code == 200


@pytest.mark.parametrize("flaw", ["expired", "signature", "audience", "issuer", "version"])
def test_bad_tokens_denied(ctx, flaw):
    now = datetime.now(timezone.utc)
    claims = {"sub": ctx.users["alice"].id, "ver": 1, "iat": now, "nbf": now, "exp": now + timedelta(hours=1),
              "iss": BusinessConfig.jwt_issuer, "aud": BusinessConfig.jwt_audience}
    secret = BusinessConfig.jwt_secret
    if flaw == "expired": claims["exp"] = now - timedelta(hours=1)
    if flaw == "signature": secret = "wrong-secret-" * 5
    if flaw == "audience": claims["aud"] = "elsewhere"
    if flaw == "issuer": claims["iss"] = "elsewhere"
    if flaw == "version": claims["ver"] = 2
    token = jwt.encode(claims, secret, algorithm="HS256")
    assert ctx.client.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_org_crud_duplicate_codes_cycles_and_member_protection(ctx):
    body = {"code": ctx.prefix + "new", "name": "新增部门"}
    d = ctx.call("POST", "/api/org/departments", "admin", json=body)
    assert d.status_code == 201, d.text
    assert ctx.call("POST", "/api/org/departments", "admin", json=body).status_code == 409
    assert ctx.call("DELETE", "/api/org/departments/" + d.json()["id"], "admin").status_code == 200
    tech, dev = ctx.departments["tech"], ctx.departments["dev"]
    for parent in [tech.id, dev.id]:
        assert ctx.call("PUT", "/api/org/departments/" + tech.id, "admin", json={"code": tech.code, "name": tech.name, "parent_id": parent}).status_code == 422
    assert ctx.call("DELETE", "/api/org/departments/" + tech.id, "admin").status_code == 409
    tree = ctx.call("GET", "/api/org/departments", "admin").json()["items"]
    assert any(d["id"] == tech.id and any(child["id"] == dev.id for child in d["children"]) for d in tree)
    role_body = {"role_code": ctx.prefix + "new", "role_name": "新角色"}
    role = ctx.call("POST", "/api/org/roles", "admin", json=role_body)
    assert role.status_code == 201
    role_id = role.json()["id"]
    assert ctx.call("POST", "/api/org/roles", "admin", json=role_body).status_code == 409
    assert ctx.call("PUT", "/api/org/roles/" + role_id, "admin", json={**role_body, "role_name": "编辑角色"}).status_code == 200
    assert ctx.call("POST", f"/api/org/roles/{role_id}/permissions", "admin", json={"permission_codes": ["unregistered"]}).status_code == 422
    assert ctx.call("DELETE", f"/api/org/roles/{role_id}", "admin").status_code == 200
    assert ctx.call("DELETE", f"/api/org/roles/{ctx.roles['employee'].id}", "admin").status_code == 409
    new_user = {"username": ctx.prefix + "new", "display_name": "新用户", "password": PASSWORD, "role_ids": [ctx.roles["employee"].id]}
    assert ctx.call("POST", "/api/org/users", "admin", json=new_user).status_code == 201
    assert ctx.call("POST", "/api/org/users", "admin", json=new_user).status_code == 409
    assert ctx.call("GET", "/api/org/users?search=" + new_user["username"], "admin").json()["total"] == 1
    assert ctx.call("PUT", "/api/org/users/" + ctx.users["bob"].id, "admin", json={"display_name": "x", "role_ids": []}).status_code == 422


def test_operation_separation_prevents_user_create_privilege_escalation(ctx):
    role = ctx.roles["employee"]
    r = ctx.call("POST", f"/api/org/roles/{role.id}/permissions", "admin", json={"permission_codes": ["org:user:create"]})
    assert r.status_code == 200
    body = {"username": ctx.prefix + "escalation", "password": PASSWORD, "display_name": "x", "role_ids": [ctx.roles["admin"].id]}
    assert ctx.call("POST", "/api/org/users", json=body).status_code == 403
    body["role_ids"] = []
    assert ctx.call("POST", "/api/org/users", json=body).status_code == 201


def test_session_owner_is_server_identity(ctx):
    r = ctx.call("POST", "/api/ai/sessions", json={"title": "私有会话"})
    assert r.status_code == 201
    session_id = r.json()["id"]
    assert r.json()["owner_id"] == ctx.users["alice"].id
    assert ctx.call("GET", "/api/ai/sessions/" + session_id).status_code == 200
    for name in ["bob", "admin"]:
        assert ctx.call("GET", "/api/ai/sessions/" + session_id, name).status_code == 404
        assert ctx.call("DELETE", "/api/ai/sessions/" + session_id, name).status_code == 404
        assert session_id not in str(ctx.call("GET", "/api/ai/sessions", name).json())
    assert ctx.call("POST", "/api/ai/sessions", json={"owner_id": ctx.users["bob"].id}).status_code == 422
    assert ctx.call("DELETE", "/api/ai/sessions/" + session_id).status_code == 200
    assert ctx.call("GET", "/api/ai/sessions/" + session_id).status_code == 404


def test_files_tasks_and_batches_ownership(ctx):
    db = ctx.db
    file = m.StoredFile(owner_id=ctx.users["alice"].id, file_name="private.md", object_key=uuid4().hex, bucket="test")
    batch = m.ImportBatch(owner_id=ctx.users["alice"].id, idempotency_key=uuid4().hex)
    db.add_all([file, batch]); db.flush()
    task = m.ImportTask(owner_id=ctx.users["alice"].id, batch_id=batch.id, file_id=file.id, idempotency_key=uuid4().hex)
    db.add(task)
    db.add(m.RolePermission(role_id=ctx.roles["employee"].id, permission_code="knowledge:task:read", permission_type="operation"))
    db.commit()
    for resource, resource_id in [("files", file.id), ("tasks", task.id), ("batches", batch.id)]:
        path = f"/api/knowledge/{resource}/{resource_id}"
        assert ctx.call("GET", path).status_code == 200
        assert ctx.call("GET", path, "bob").status_code == 404
    assert ctx.call("GET", f"/api/knowledge/tasks/{task.id}", "admin").status_code == 200
    assert ctx.call("GET", f"/api/knowledge/files/{file.id}", "admin").status_code == 404
    u = ctx.unit([("user", ctx.users["alice"].id)])
    file.unit_id, file.version_id = u.id, u.active_version_id
    db.commit()
    r = ctx.call("GET", f"/api/knowledge/files/{file.id}")
    assert r.status_code == 200 and "object_key" not in r.text
    ctx.call("POST", f"/api/knowledge/units/{u.id}/permissions", "kb", json={"grants": []})
    assert ctx.call("GET", f"/api/knowledge/files/{file.id}").status_code == 404  # Even its uploader.


def test_database_enforces_unit_version_and_owner_relations(ctx):
    u1, u2 = ctx.unit(), ctx.unit()
    with pytest.raises(IntegrityError):
        with ctx.db.begin_nested():
            ctx.db.add(m.KnowledgeChunk(unit_id=u1.id, version_id=u2.active_version_id, chunk_index=0, content="x"))
            ctx.db.flush()
    with pytest.raises(IntegrityError):
        with ctx.db.begin_nested():
            u1.active_version_id = u2.active_version_id
            ctx.db.flush()
    session = m.ChatSession(owner_id=ctx.users["alice"].id)
    ctx.db.add(session); ctx.db.flush()
    with pytest.raises(IntegrityError):
        with ctx.db.begin_nested():
            ctx.db.add(m.QAAccessLog(session_id=session.id, user_id=ctx.users["bob"].id, question="x"))
            ctx.db.flush()
    file = m.StoredFile(owner_id=ctx.users["bob"].id, file_name="x", object_key=uuid4().hex, bucket="test")
    batch = m.ImportBatch(owner_id=ctx.users["alice"].id, idempotency_key=uuid4().hex)
    ctx.db.add_all([file, batch]); ctx.db.flush()
    with pytest.raises(IntegrityError):
        with ctx.db.begin_nested():
            ctx.db.add(m.ImportTask(owner_id=ctx.users["alice"].id, file_id=file.id, batch_id=batch.id, idempotency_key=uuid4().hex))
            ctx.db.flush()


def test_legacy_routes_are_closed(ctx):
    from atguigu.web.api import import_service, query_service
    for legacy_app, routes in [
        (import_service.app, [("POST", "/upload"), ("GET", "/status/known")]),
        (query_service.app, [("POST", "/query"), ("GET", "/history/known"), ("DELETE", "/history/known"), ("GET", "/stream/known")]),
    ]:
        assert legacy_data_closed not in legacy_app.dependency_overrides
        legacy_app.dependency_overrides[get_db] = ctx.dependency
        try:
            with TestClient(legacy_app) as client:
                for method, path in routes:
                    assert client.request(method, path).status_code == 401
                    assert client.request(method, path, headers=ctx.headers()).status_code == 410
        finally:
            legacy_app.dependency_overrides.clear()


def test_mysql_session_utc(ctx, engine):
    if engine.dialect.name != "mysql":
        pytest.skip("MySQL session check only")
    assert ctx.db.scalar(text("SELECT @@session.time_zone")) == "+00:00"


def test_seed_repeat_preserves_changed_accounts_and_revoked_permissions(tmp_path):
    from atguigu.business.seed import seed_demo, USERS
    engine = make_engine("sqlite:///" + str(tmp_path / "seed.db"))
    m.Base.metadata.create_all(engine)
    passwords = {username: PASSWORD for username, *_ in USERS}
    with Session(engine) as db:
        assert len(seed_demo(db, passwords)) == 7
        db.commit()
        user = db.scalar(select(m.User).where(m.User.username == "alice"))
        user.status = "disabled"
        user.display_name = "用户自行修改"
        user.password_hash = hash_password(PASSWORD + "-changed")
        expected_hash = user.password_hash
        role = db.scalar(select(m.Role).where(m.Role.role_code == "employee"))
        from sqlalchemy import delete
        db.execute(delete(m.RolePermission).where(m.RolePermission.role_id == role.id))
        db.commit()
        assert seed_demo(db, passwords) == []
        db.commit()
        db.refresh(user)
        assert user.status == "disabled" and user.display_name == "用户自行修改" and user.password_hash == expected_hash
        assert db.scalar(select(func.count()).select_from(m.RolePermission).where(m.RolePermission.role_id == role.id)) == 0
        # A same-name user from a different installation must not be adopted.
        db.add(m.User(id=str(uuid4()), username="conflict", display_name="original", password_hash=PASSWORD_HASH))
        db.commit()
        from atguigu.business.seed import ensure_owned
        with pytest.raises(ValueError, match="未覆盖"):
            ensure_owned(db, m.User, "username", "conflict", str(uuid4()))
    engine.dispose()
