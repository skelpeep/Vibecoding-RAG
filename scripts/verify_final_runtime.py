"""Read-only final process, database and periodic-worker snapshot."""
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import httpx
from sqlalchemy import func, select, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business.chat_service import session_factory
from atguigu.business import models as m
from atguigu.business.faq_cache import client


def main():
    manifest = json.loads((ROOT / "var/logs/project-processes.json").read_text(encoding="utf-8-sig"))
    process_result = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process | Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress"],
        capture_output=True, encoding="utf8", check=True)
    live = {p["ProcessId"]: p for p in json.loads(process_result.stdout)}
    processes = [{"service": record["service"], "pid": record["pid"],
                  "running": record["pid"] in live and live[record["pid"]]["ExecutablePath"] == manifest["python"]}
                 for record in manifest["processes"]]
    ready = httpx.get(f"http://127.0.0.1:{manifest['port']}/ready").json()
    assert ready["database_revision"] == "0005"
    assert client().ping()
    with session_factory() as db:
        counts = {"users": db.scalar(select(func.count()).select_from(m.User)),
                  "roles": db.scalar(select(func.count()).select_from(m.Role)),
                  "departments": db.scalar(select(func.count()).select_from(m.Department)),
                  "undeleted_knowledge": db.scalar(select(func.count()).select_from(m.KnowledgeUnit).where(m.KnowledgeUnit.status != "deleted")),
                  "processing_chat": db.scalar(select(func.count()).select_from(m.QAAccessLog).where(m.QAAccessLog.status == "processing")),
                  "pending_outbox": db.scalar(select(func.count()).select_from(m.OutboxEvent).where(m.OutboxEvent.processed_at.is_(None)))}
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
    mining = []
    for log in sorted((ROOT / "var/logs").glob("settlement-worker-*.out.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:2]:
        for line in log.read_text(encoding="utf8").splitlines()[-3:]:
            try:
                value = ast.literal_eval(line).get("settlement")
                if isinstance(value, dict):
                    mining.append(value)
            except (SyntaxError, ValueError):
                pass
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "origin": f"http://127.0.0.1:{manifest['port']}",
              "processes": processes, "ready": ready, "revision": revision, "business_tables": len(m.Base.metadata.tables),
              "redis_ping": True, "counts": counts, "recent_periodic_mining": mining,
              "passed": all(p["running"] for p in processes) and len(processes) == 3 and bool(mining) and counts["processing_chat"] == 0}
    (ROOT / "docs/evidence/stage7/runtime.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    assert report["passed"], "Final runtime checks incomplete"
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
