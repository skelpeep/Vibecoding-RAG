"""Real SSE controls with existing isolated stage-five fixture knowledge.

Requests use new owned sessions. Only the fixture private unit's grants change;
the original exact grants are restored even when a check fails. No service kill.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business.database import get_engine
from atguigu.business.models import QAAccessLog
from atguigu.business.seed import seed_id
from verify_stage5_http import parse_sse

BASE = os.getenv("STAGE5_API_BASE", "http://127.0.0.1:8104")
OUT = ROOT / "docs/evidence/stage5"


def main():
    fixtures = json.loads((OUT / "fixtures.json").read_text(encoding="utf-8"))
    creds = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    private_id = fixtures["unit_ids"][1]
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "passed": False,
              "method": "real HTTP SSE/MySQL/Mongo/provider controls", "checks": [], "requests": [],
              "sessions": [], "grants_restored": False}
    controls = httpx.Client(base_url=BASE, timeout=180, trust_env=False)
    streams = httpx.Client(base_url=BASE, timeout=180, trust_env=False)
    heads = {}
    original_grants = None

    def save():
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "stream-controls.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def req(method, path, actor="alice", status=200, **kwargs):
        response = controls.request(method, path, headers=heads[actor], **kwargs)
        assert response.status_code == status, f"{method} {path}: HTTP {response.status_code}"
        return response

    def check(name):
        report["checks"].append(name)
        save()
        print("PASS " + name, flush=True)

    def record(meta, events):
        rid, sid = meta["request_id"], meta["session_id"]
        report["sessions"].append(sid)
        with Session(get_engine()) as db:
            log = db.get(QAAccessLog, rid)
            row = {"request_id": rid, "session_id": sid, "status": log.status,
                   "reason": log.details_json.get("reason"), "duration_ms": log.response_time_ms,
                   "first_token_ms": log.first_token_ms, "model_usage": log.model_usage_json,
                   "usage_completeness": log.details_json.get("usage_completeness"),
                   "recalled": log.recalled_unit_ids_json, "allowed": log.authorized_unit_ids_json,
                   "denied": log.unauthorized_unit_ids_json, "cited": log.cited_sources_json,
                   "event_names": [event["event"] for event in events],
                   "end": events[-1]["data"]}
            assert log.finished_at and log.response_time_ms is not None
            assert log.status == events[-1]["data"]["status"]
            assert log.cited_sources_json == [], "Interrupted answer must have zero actual citations"
        report["requests"].append(row)
        save()
        return row

    try:
        for actor in ("alice", "kb_admin"):
            login = controls.post("/api/auth/login", json={"username": actor, "password": creds[actor]})
            login.raise_for_status()
            heads[actor] = {"Authorization": "Bearer " + login.json()["access_token"]}
        ready = controls.get("/ready")
        assert ready.status_code == 200 and ready.json()["database_revision"] == "0004"
        # The permission endpoint returns existing explicit grants only to owner
        # operations. Snapshot exact target IDs, never assume the fixture recipe.
        detail = req("GET", f"/api/knowledge/units/{private_id}", "kb_admin").json()
        original_grants = [{"target_type": grant["target_type"], "target_id": grant["target_id"]}
                           for grant in detail["grants"]]
        question = fixtures["question"]

        with streams.stream("POST", "/api/ai/chat/stream", headers=heads["alice"], json={"question": question}) as response:
            assert response.status_code == 200
            iterator = parse_sse(response.iter_lines())
            events = [next(iterator)]
            meta = events[0]["data"]
            report["sessions"].append(meta["session_id"])
            req("POST", "/api/ai/chat/stream", status=409,
                json={"question": "同会话并发请求应冲突", "session_id": meta["session_id"]})
            check("open real SSE session rejects a second request with409")
            req("POST", f"/api/ai/chat/requests/{meta['request_id']}/cancel")
            events.extend(iterator)
        assert events[-1]["event"] == "end" and events[-1]["data"]["status"] == "cancelled"
        assert any(event["event"] == "permission" and event["data"].get("clear_answer") for event in events)
        row = record(meta, events)
        assert row["status"] == "cancelled" and row["reason"] == "cancel_requested"
        check("explicit server cancellation ends stream and persists cancelled with zero actual citations")

        changed = False
        events = []
        with streams.stream("POST", "/api/ai/chat/stream", headers=heads["alice"], json={"question": question}) as response:
            assert response.status_code == 200
            for event in parse_sse(response.iter_lines()):
                events.append(event)
                if event["event"] == "meta":
                    meta = event["data"]
                    report["sessions"].append(meta["session_id"])
                if event["event"] == "delta" and not changed:
                    # Revoke only this verification fixture from Alice, leaving
                    # author management and all other explicit grants intact.
                    retained = [grant for grant in original_grants
                                if not (grant["target_type"] == "user" and grant["target_id"] == seed_id("user/alice"))]
                    req("POST", f"/api/knowledge/units/{private_id}/permissions", "kb_admin",
                        json={"grants": retained})
                    changed = True
        assert changed, "Expected an actual provider delta before revocation"
        assert events[-1]["event"] == "end" and events[-1]["data"]["status"] == "restricted"
        permission_index = next(index for index, event in enumerate(events)
            if event["event"] == "permission" and event["data"].get("clear_answer"))
        assert not any(event["event"] == "delta" for event in events[permission_index + 1:])
        row = record(meta, events)
        assert row["reason"] == "permission_changed"
        history = req("GET", f"/api/ai/chat/sessions/{meta['session_id']}/messages").json()
        turn = next(turn for turn in history["items"] if turn["request_id"] == meta["request_id"])
        assert turn["user"]["redacted"] and turn["assistant"]["redacted"]
        assert not turn["user"]["content"] and not turn["assistant"]["content"]
        check("revocation after real provider delta clears answer ends restricted and redacts entire turn")
        report["passed"] = True
    finally:
        if original_grants is not None:
            req("POST", f"/api/knowledge/units/{private_id}/permissions", "kb_admin",
                json={"grants": original_grants})
            report["grants_restored"] = True
        for sid in set(report["sessions"]):
            req("DELETE", f"/api/ai/chat/sessions/{sid}", status=204)
        report["sessions_closed"] = True
        save()
        controls.close()
        streams.close()
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
