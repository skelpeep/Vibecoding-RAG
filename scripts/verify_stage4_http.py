"""Real HTTP/MySQL/MinIO/Milvus/embedding acceptance; only generated test units.

The intentionally corrupted replacement source is a labelled fault-injection check.
No substitute model vectors are inserted. Units are soft-deleted through the API.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business.database import get_engine
from atguigu.business.models import ImportTask, KnowledgeChunk, OutboxEvent, StoredFile
from atguigu.business.knowledge_storage import get_storage
from atguigu.business.knowledge_index import get_index
from atguigu.business.seed import seed_id
from atguigu.config.config import MinIoConfig
from atguigu.tool.embedding_client_tool import get_embeddings

BASE = os.getenv("STAGE4_API_BASE", "http://127.0.0.1:8103")
OUT = ROOT / "docs/evidence/stage4"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    run_id = uuid4().hex[:12]
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "run_id": run_id,
              "services": "real HTTP, MySQL, MinIO, Milvus and Qwen3 embedding API", "checks": [], "units": [], "cleanup": False}
    client = httpx.Client(base_url=BASE, timeout=90, trust_env=False)
    users = {}

    def checked(name, **evidence):
        report["checks"].append({"name": name, **evidence})
        print("PASS " + name, flush=True)

    def req(method, path, *, who="kb_admin", expected=200, **kwargs):
        result = client.request(method, "/api/knowledge" + path, headers=users[who], **kwargs)
        assert result.status_code == expected, f"{method} {path} HTTP {result.status_code}: {result.text[:200]}"
        return result

    def worker():
        with (OUT / "http-worker.log").open("a", encoding="utf-8") as log:
            process = subprocess.run([sys.executable, "-m", "atguigu.cli", "worker", "--once"], cwd=ROOT,
                                     stdout=log, stderr=log, timeout=360, env={**os.environ, "PYTHONUTF8": "1"})
        assert process.returncode == 0, "Worker execution failed; see http-worker.log"

    try:
        assert client.get("/ready").json()["database_revision"] == "0003"
        assert client.get("/api/knowledge/units").status_code == 401
        for name in ("kb_admin", "admin", "alice", "bob", "carol"):
            response = client.post("/api/auth/login", json={"username": name, "password": credentials[name]})
            assert response.status_code == 200
            users[name] = {"Authorization": "Bearer " + response.json()["access_token"]}
        checked("ready 0003 and anonymous denied")
        paths = [ROOT / "examples/stage4" / name for name in (
            "技术变更流程.md", "客户资料交接.txt", "知识发布检查.docx", "release-checklist.pdf")]
        files = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
        files += [("files", ("技术变更流程.md", "# 同名独立文档（示例）\n这个文档来自第二个目录，不覆盖第一篇。".encode(), "text/markdown")),
                  ("files", ("旧文件.doc", b"unsupported demo", "application/msword"))]
        data = {"idempotency_key": "stage4-http-" + run_id,
                "relative_paths": json.dumps(["a/" + p.name for p in paths] + ["b/技术变更流程.md", "b/旧文件.doc"]),
                "category": "阶段四验收 " + run_id}
        batch = req("POST", "/import", data=data, files=files, expected=202).json()
        report["batch_id"] = batch["id"]
        report["units"] = [t["unit_id"] for t in batch["tasks"]]
        replay = req("POST", "/import", data=data, files=files, expected=202).json()
        assert replay["id"] == batch["id"]
        assert {t["id"] for t in replay["tasks"]} == {t["id"] for t in batch["tasks"]}
        assert len(set(report["units"])) == 6
        checked("directory metadata, mixed batch, same-name isolation and HTTP idempotency", files=6)
        req("GET", "/batches/" + batch["id"], who="alice", expected=403)
        admin_view = req("GET", "/batches/" + batch["id"], who="admin").json()
        assert all("file_name" not in t and "unit_id" not in t for t in admin_view["tasks"])
        checked("other user denied and task administrator sees no file details")
        worker()
        done = req("GET", "/batches/" + batch["id"]).json()
        report["batch_result"] = done
        assert done["status"] == "partial_failed", done["status"]
        assert done["counts"]["completed"] == 5 and done["counts"]["failed"] == 1, done["counts"]
        failed = next(t for t in done["tasks"] if t["status"] == "failed")
        assert failed["error_code"] == "LEGACY_DOC_UNSUPPORTED"
        checked("real MD TXT DOCX text-PDF indexing and partial failure", counts=done["counts"])
        task = next(t for t in done["tasks"] if t["file_name"] == "技术变更流程.md" and t["relative_path"].startswith("a/"))
        uid, vid = task["unit_id"], task["version_id"]
        for name in ("alice", "bob", "admin"):
            req("GET", "/units/" + uid, who=name, expected=404)
        req("POST", f"/units/{uid}/versions/{vid}/activate")
        req("POST", f"/units/{uid}/status", json={"status": "published"})
        req("GET", "/units/" + uid, who="alice", expected=404)
        checked("default deny survives activation and publication")
        attachment_bytes = b"stage4 confidential attachment\n"
        attachment = req("POST", f"/units/{uid}/attachments", expected=201,
                         files={"file": ("verification.txt", attachment_bytes, "text/plain")}).json()
        grant = {"grants": [{"target_type": "department", "target_id": seed_id("department/demo-tech")},
                            {"target_type": "user", "target_id": seed_id("user/bob")}]}
        req("POST", f"/units/{uid}/permissions", json=grant)
        for name in ("alice", "bob"):
            detail = req("GET", "/units/" + uid, who=name).json()
            assert "技术变更" in detail["content"]
            assert req("GET", f"/files/{attachment['id']}/download", who=name).content == attachment_bytes
        req("GET", "/units/" + uid, who="carol", expected=404)
        req("GET", "/units/" + uid, who="admin", expected=404)
        checked("department OR personal grants with non-inheriting department tree and private attachment")
        with Session(get_engine()) as db:
            source = db.get(StoredFile, db.get(ImportTask, task["id"]).file_id)
            chunks = list(db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.version_id == vid)))
            assert chunks and all(c.unit_id == uid and c.vector_id for c in chunks)
            vector_ids = [c.vector_id for c in chunks]
            source_key, bucket = source.object_key, source.bucket
        anonymous = httpx.get(f"http{'s' if MinIoConfig.secure else ''}://{MinIoConfig.minio_endpoint}/{bucket}/{source_key}", timeout=10, trust_env=False)
        assert anonymous.status_code == 403
        index = get_index(); index.ensure_collection(); index.verify(vector_ids)
        vector = get_embeddings(["技术变更需要提前多久提交？"])["dense"][0]
        hits = index.client.search(index.collection, data=[vector], anns_field="dense_vector",
                                   filter='version_id == "' + vid + '"', limit=5,
                                   output_fields=["unit_id", "version_id", "chunk_id"], consistency_level="Strong")
        assert hits and hits[0] and hits[0][0]["entity"]["unit_id"] == uid
        checked("private MinIO 403 and real semantic vector search with source IDs", chunks=len(chunks), hits=len(hits[0]))
        first = req("GET", "/units/" + uid).json()
        update = req("PUT", "/units/" + uid, json={"title": "未发布修改 " + run_id, "content": "新版本（验收）\n变更应提前两个工作日提交。", "category": "阶段四验收 " + run_id, "tags": ["版本测试"]}).json()
        new_vid = update["latest_version"]["id"]
        # Corrupt only this generated test task's source; the worker must fail closed.
        with Session(get_engine()) as db:
            new_task = db.get(ImportTask, update["task_id"])
            source = db.get(StoredFile, new_task.file_id)
            get_storage().put_bytes(source.object_key, b"deliberately corrupted QA object", source.content_type)
        worker()
        failure = req("GET", "/tasks/" + update["task_id"]).json()
        assert failure["status"] == "failed" and failure["error_code"] == "SOURCE_INTEGRITY"
        current = req("GET", "/units/" + uid, who="alice").json()
        assert current["active_version_id"] == vid and current["title"] == first["title"] and "两个" not in current["content"]
        req("POST", f"/units/{uid}/versions/{new_vid}/activate", expected=409)
        checked("injected source corruption fails and preserves published title/content/version")
        rebuilt = req("POST", f"/units/{uid}/versions/{vid}/rebuild", expected=202).json()
        worker()
        ready = req("GET", "/tasks/" + rebuilt["task_id"]).json()
        assert ready["status"] == "completed", ready
        replacement = ready["version_id"]
        req("POST", f"/units/{uid}/versions/{replacement}/activate")
        current = req("GET", "/units/" + uid, who="alice").json()
        assert current["active_version_id"] == replacement
        new_attachment = next(a for a in current["attachments"] if a["file_name"] == "verification.txt")
        assert req("GET", f"/files/{new_attachment['id']}/download", who="alice").content == attachment_bytes
        req("GET", f"/files/{attachment['id']}/download", who="alice", expected=404)
        checked("real version rebuild, explicit activation, inherited attachment and old-file rejection")
        req("POST", f"/units/{uid}/permissions", json={"grants": []})
        req("GET", "/units/" + uid, who="alice", expected=404)
        req("GET", f"/files/{new_attachment['id']}/download", who="alice", expected=404)
        checked("revocation immediately denies body and existing attachment URL")
        for kind, target in (("role", seed_id("role/engineer")), ("global", "*")):
            req("POST", f"/units/{uid}/permissions", json={"grants": [{"target_type": kind, "target_id": target}]})
            assert req("GET", "/units/" + uid, who="alice").status_code == 200
        checked("role and global grants independently allow authorized readers")
        for status in ("draft", "disabled"):
            req("POST", f"/units/{uid}/status", json={"status": status})
            result = req("POST", "/check-permissions", who="alice", json={"unit_ids": [uid]}).json()
            assert result["authorized_unit_ids"] == []
            req("GET", "/units/" + uid, who="alice", expected=404)
            req("GET", f"/files/{new_attachment['id']}/download", who="alice", expected=404)
        checked("unpublish and disable immediately exclude retrieval authorization and files")
        with Session(get_engine()) as db:
            events = set(db.scalars(select(OutboxEvent.event_type).where(OutboxEvent.aggregate_id == uid)))
        assert {"unit.permissions.changed", "unit.version.activated", "unit.status.changed"} <= events
        checked("durable invalidation events recorded; FAQ consumer intentionally future scope")
        report["passed"] = True
    except Exception as error:
        report["passed"] = False
        report["failure"] = {"type": type(error).__name__, "detail": str(error)[:700]}
        print("FAIL " + type(error).__name__ + ": " + str(error)[:300], flush=True)
    finally:
        if report["units"] and "kb_admin" in users:
            try:
                req("DELETE", "/units", json={"unit_ids": report["units"]})
                report["cleanup"] = True
            except Exception:
                report["cleanup"] = False
        client.close()
        (OUT / "http.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report.get("passed") and report["cleanup"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
