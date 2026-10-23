"""Read-only real optional HyDE pipeline probe with an exact temporary API session.

This calls real LLM, embeddings, reranker, MySQL and Milvus. It never changes
knowledge grants/content or fabricates vector results. It is separate from the
HTTP/SSE audit suite because the pipeline is called directly to enable HyDE for
this single run without modifying the API process configuration.
"""
import asyncio
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
from atguigu.business.models import ChatSession, KnowledgeChunk, KnowledgeUnit, User
from atguigu.business.rag import RagPipeline
from atguigu.config.config import RagConfig


class HyDEConfig(RagConfig):
    hyde_enabled = True
    web_enabled = False


def main():
    output = ROOT / "docs/evidence/stage5/hyde.json"
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "passed": False,
              "services": "real API session/MySQL/Milvus/LLM/embedding/rerank", "direct_pipeline": True,
              "hyde_enabled": True, "web_enabled": False, "question": "项目资料归档需要提前多久提交？",
              "session_deleted": False, "checks": []}
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    session_id = None
    with httpx.Client(base_url=os.getenv("STAGE5_API_BASE", "http://127.0.0.1:8104"),
                      timeout=180, trust_env=False) as client:
        try:
            login = client.post("/api/auth/login", json={"username": "alice", "password": credentials["alice"]})
            login.raise_for_status()
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            created = client.post("/api/ai/chat/sessions", json={"title": "阶段五临时真实 HyDE 验证"}, headers=headers)
            created.raise_for_status()
            session_id = created.json()["id"]
            report["session_id"] = session_id
            with Session(get_engine()) as db:
                record = db.get(ChatSession, session_id)
                user = db.get(User, record.owner_id)
                user_id, token_version = user.id, user.token_version
            events = []
            async def delta(text): events.append(text)
            pipeline = RagPipeline(config=HyDEConfig)
            result = asyncio.run(pipeline.run(user_id, session_id, report["question"],
                                             token_version=token_version, on_delta=delta))
            report["status"] = result.status
            report["answer"] = result.answer
            report["sources"] = result.sources
            report["usage"] = result.usage
            report["metrics"] = result.metrics
            report["degradations"] = result.degradations
            report["stream_delta_count"] = len(events)
            assert result.status == "completed", result.status
            assert result.usage["hyde"][0]["status"] == "completed"
            assert result.usage["hyde"][0]["known"]
            assert len(result.usage["embedding"]) == 2
            assert all(entry["status"] == "completed" and entry["known"] for entry in result.usage["embedding"])
            assert result.usage["generation"][0]["known"]
            report["checks"].append("Real hypothesis LLM plus two real embedding calls and provider generation usage")
            assert result.metrics["dense_recalled_count"] > 0 and result.metrics["hyde_recalled_count"] > 0
            assert result.metrics["invalid_vector_count"] == 0
            report["checks"].append("Real Milvus named-primary-key hits validated and contributed to both dense and HyDE recall")
            assert result.sources and all(source["source_type"] == "institutional" for source in result.sources)
            with Session(get_engine()) as db:
                for source in result.sources:
                    chunk = db.get(KnowledgeChunk, source["chunk_id"])
                    unit = db.get(KnowledgeUnit, source["unit_id"])
                    assert unit.status == "published" and unit.active_version_id == source["version_id"]
                    assert chunk.unit_id == source["unit_id"] and chunk.version_id == source["version_id"]
                    assert source["snippet"] in chunk.content
            report["checks"].append("All actual citations are current MySQL knowledge chunks; HyDE text is never cited")
            assert "三" in result.answer or "3" in result.answer
            # A short real provider answer may arrive in a single content delta.
            # Streaming is a transport contract, not a minimum chunk count.
            assert events and "".join(events) == result.answer
            report["checks"].append("Real streamed answer states the archived-document deadline with institutional citation")
            report["passed"] = True
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error"] = str(exc)[:200]
            raise
        finally:
            if session_id:
                response = client.delete("/api/ai/chat/sessions/" + session_id, headers=headers)
                report["session_deleted"] = response.status_code == 204
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS real optional HyDE; current MySQL citations and actual provider usage; temporary session deleted", flush=True)


def semantic_denied():
    """No lexical overlap: independent real denied dense probe returns a count."""
    output = ROOT / "docs/evidence/stage5/semantic-denied.json"
    credentials = json.loads((ROOT / "var/setup/stage2-accounts.json").read_text(encoding="utf-8"))
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "passed": False,
              "services": "real API session/MySQL/Milvus/embedding", "direct_pipeline": True,
              "question": "材料应在完工之前多早递交？", "session_deleted": False}
    session_id = None
    with httpx.Client(base_url=os.getenv("STAGE5_API_BASE", "http://127.0.0.1:8104"),
                      timeout=180, trust_env=False) as client:
        try:
            login = client.post("/api/auth/login", json={"username": "carol", "password": credentials["carol"]})
            login.raise_for_status()
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            created = client.post("/api/ai/chat/sessions", json={"title": "阶段五临时语义拒绝验证"}, headers=headers)
            created.raise_for_status()
            session_id = created.json()["id"]
            with Session(get_engine()) as db:
                session = db.get(ChatSession, session_id)
                user = db.get(User, session.owner_id)
                user_id, token_version = user.id, user.token_version
            result = asyncio.run(RagPipeline().run(user_id, session_id, report["question"], token_version=token_version))
            report.update(status=result.status, answer=result.answer, sources=result.sources,
                          permission_hint=result.permission_hint, metrics=result.metrics, usage=result.usage)
            assert result.status == "restricted" and not result.sources
            assert result.permission_hint["denied_count"] > 0
            assert result.metrics["lexical_recalled_count"] == 0 and not result.metrics["authorized_unit_ids"]
            assert "generation" not in result.usage and "rerank" not in result.usage
            assert result.metrics["invalid_vector_count"] == 0
            report["passed"] = True
        except Exception as exc:
            report["error_type"] = type(exc).__name__
            report["error"] = str(exc)[:200]
            raise
        finally:
            if session_id:
                report["session_deleted"] = client.delete("/api/ai/chat/sessions/" + session_id, headers=headers).status_code == 204
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS real semantic-only denied probe; no knowledge rerank/generation; temporary session deleted", flush=True)


if __name__ == "__main__":
    if "--semantic-only" in sys.argv:
        semantic_denied()
    else:
        main()
