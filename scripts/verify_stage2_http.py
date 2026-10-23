"""Real loopback HTTP smoke test. Never writes passwords, JWTs or content to evidence."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import func, inspect, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business.database import get_engine
from atguigu.business.models import Base, User
from atguigu.config.config import RuntimeConfig


def main():
    (ROOT / "docs/evidence/stage2").mkdir(parents=True, exist_ok=True)
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "checks": {}}
    checks = report["checks"]
    with httpx.Client(base_url=f"http://127.0.0.1:{RuntimeConfig.platform_port}", timeout=10, trust_env=False) as client:
        checks["health"] = client.get("/health").status_code
        checks["ready"] = client.get("/ready").status_code
        checks["docs"] = client.get("/docs").status_code
        checks["anonymous_denied"] = client.get("/api/auth/me").status_code
        tokens = {}
        for username in ["admin", "kb_admin", "alice", "bob", "carol", "no_op_demo"]:
            response = client.post("/api/auth/login", json={"username": username, "password": credentials[username]})
            assert response.status_code == 200, username
            tokens[username] = {"Authorization": "Bearer " + response.json()["access_token"]}
        checks["active_demo_logins"] = len(tokens)
        checks["disabled_login"] = client.post("/api/auth/login", json={"username": "disabled_demo", "password": credentials["disabled_demo"]}).status_code
        checks["organization_admin"] = client.get("/api/org/users", headers=tokens["admin"]).status_code
        checks["ordinary_org_denied"] = client.get("/api/org/users", headers=tokens["alice"]).status_code
        checks["no_operation_denied"] = client.post("/api/knowledge/check-permissions", headers=tokens["no_op_demo"], json={"unit_ids": [str(uuid4())]}).status_code
        missing = str(uuid4())
        result = client.post("/api/knowledge/check-permissions", headers=tokens["admin"], json={"unit_ids": [missing]})
        checks["default_deny_admin"] = result.json() == {"authorized_unit_ids": [], "unauthorized_unit_ids": [missing]}
        checks["forged_identity"] = client.post("/api/knowledge/check-permissions", headers=tokens["alice"], json={"unit_ids": [missing], "user_id": "admin"}).status_code
        session = client.post("/api/ai/sessions", headers=tokens["alice"], json={"title": "阶段二 HTTP 归属验证"})
        assert session.status_code == 201
        session_id = session.json()["id"]
        try:
            checks["own_session"] = client.get("/api/ai/sessions/" + session_id, headers=tokens["alice"]).status_code
            checks["other_session_denied"] = client.get("/api/ai/sessions/" + session_id, headers=tokens["bob"]).status_code
            checks["admin_session_denied"] = client.get("/api/ai/sessions/" + session_id, headers=tokens["admin"]).status_code
        finally:
            checks["session_soft_deleted"] = client.delete("/api/ai/sessions/" + session_id, headers=tokens["alice"]).status_code
        for service, port, path in [("import", RuntimeConfig.import_port, "/status/known"), ("query", RuntimeConfig.query_port, "/history/known")]:
            response = client.get(f"http://127.0.0.1:{port}{path}")
            checks[service + "_legacy_anonymous_denied"] = response.status_code
            response = client.get(f"http://127.0.0.1:{port}{path}", headers=tokens["admin"])
            checks[service + "_legacy_authenticated_closed"] = response.status_code
        (ROOT / "docs/evidence/stage2/openapi.json").write_text(json.dumps(client.get("/openapi.json").json(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with get_engine().connect() as c:
        report["database"] = {"revision": c.scalar(text("SELECT version_num FROM alembic_version")),
                              "session_timezone": c.scalar(text("SELECT @@session.time_zone")),
                              "business_table_count": len(set(inspect(c).get_table_names()) & set(Base.metadata.tables)),
                              "user_count": c.scalar(select(func.count()).select_from(User))}
    expected = {"health": 200, "ready": 200, "docs": 200, "anonymous_denied": 401, "active_demo_logins": 6,
                "disabled_login": 401, "organization_admin": 200, "ordinary_org_denied": 403, "no_operation_denied": 403,
                "default_deny_admin": True, "forged_identity": 422, "own_session": 200, "other_session_denied": 404,
                "admin_session_denied": 404, "session_soft_deleted": 200,
                "import_legacy_anonymous_denied": 401, "query_legacy_anonymous_denied": 401,
                "import_legacy_authenticated_closed": 410, "query_legacy_authenticated_closed": 410}
    report["passed"] = checks == expected
    target = ROOT / "docs/evidence/stage2/http.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
