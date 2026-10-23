"""Remove exact UI fixtures, retain the labelled demo and smoke the final API."""
import json
import sys
from pathlib import Path

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business.database import get_engine
from atguigu.business.models import KnowledgeUnit, User, Role, Department, ImportTask


def main():
    out = ROOT / "docs/evidence/stage4"
    creds = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    ui = json.loads((out / "ui/report.json").read_text(encoding="utf-8"))
    demo = json.loads((out / "demo.json").read_text(encoding="utf-8"))
    targets = list(dict.fromkeys(ui["unit_ids"] + [demo["retry_unit_id"]]))
    report = {"deleted_qa_ids": targets, "retained_demo_id": demo["image_unit_id"], "checks": []}
    with httpx.Client(base_url="http://127.0.0.1:8103", timeout=30, trust_env=False) as client:
        response = client.post("/api/auth/login", json={"username": "kb_admin", "password": creds["kb_admin"]})
        response.raise_for_status(); owner_id = response.json()["user_info"]["id"]
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        with Session(get_engine()) as db:
            existing = list(db.scalars(select(KnowledgeUnit).where(KnowledgeUnit.id.in_(targets), KnowledgeUnit.status != "deleted")))
            assert all(u.creator_id == owner_id and (u.title.startswith(ui["prefix"]) or u.title == "重试流程（阶段四验收）") for u in existing)
            targets = [u.id for u in existing]
        if targets:
            result = client.request("DELETE", "/api/knowledge/units", json={"unit_ids": targets})
            result.raise_for_status()
        for uid in report["deleted_qa_ids"]:
            assert client.get("/api/knowledge/units/" + uid).status_code == 404
        report["checks"].append("exact UI fixtures soft deleted and inaccessible")
        assert client.get("/ready").json()["database_revision"] == "0003"
        assert client.get("/health").json()["stage"] == 4
        detail = client.get("/api/knowledge/units/" + demo["image_unit_id"]).json()
        assert detail["is_maintenance_view"] and detail["latest_version"]["status"] == "ready"
        image = next(f for f in detail["attachments"] if f["purpose"] == "image")
        assert client.get(image["image_url"]).status_code == 200
        versions = client.get("/api/knowledge/units/" + demo["image_unit_id"] + "/versions").json()
        assert versions["items"][0]["task_id"] == demo["image_task_id"]
        report["checks"].append("restarted API exposes final maintenance/task/image contract")
        token = client.post("/api/auth/login", json={"username": "alice", "password": creds["alice"]}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        assert client.get("/api/knowledge/units/" + demo["image_unit_id"], headers=headers).status_code == 404
        assert client.get(image["image_url"], headers=headers).status_code == 404
        report["checks"].append("retained demo remains draft with default reader deny")
    with Session(get_engine()) as db:
        report["database"] = {"users": db.scalar(select(func.count()).select_from(User)),
                              "roles": db.scalar(select(func.count()).select_from(Role)),
                              "departments": db.scalar(select(func.count()).select_from(Department)),
                              "visible_units": db.scalar(select(func.count()).select_from(KnowledgeUnit).where(KnowledgeUnit.status != "deleted")),
                              "revision": db.scalar(text("SELECT version_num FROM alembic_version"))}
        retry = db.get(ImportTask, demo["retry_task_id"])
        assert retry.status == "completed" and retry.attempts == 2
        report["retry_completed"] = {"task_id": retry.id, "attempts": retry.attempts, "status": retry.status}
    report["passed"] = True
    (out / "final-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
