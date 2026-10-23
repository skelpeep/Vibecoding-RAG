"""Security/quality RAG tests with isolated real SQL and explicit model/vector fakes."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from atguigu.business import models as m
from atguigu.business.database import make_engine
from atguigu.business.rag import RagPipeline, lexical_rank, reciprocal_rank_fusion
from atguigu.config.config import RagConfig


class Settings(RagConfig):
    rewrite_enabled = True
    hyde_enabled = False
    web_enabled = False
    dense_batch_size = 2
    dense_limit = 1
    dense_max_limit = 8
    lexical_scan_limit = 20
    lexical_limit = 20


@pytest.fixture
def corpus(tmp_path):
    engine = make_engine("sqlite:///" + str(tmp_path / "rag.db"))
    m.Base.metadata.create_all(engine)
    factory = lambda: Session(engine, expire_on_commit=False)
    with factory() as db:
        db.add(m.Permission(code="ai:chat", name="chat", permission_type="operation"))
        role = m.Role(role_name="employee", role_code=uuid4().hex)
        user = m.User(username=uuid4().hex, display_name="alice", password_hash="unused")
        other = m.User(username=uuid4().hex, display_name="bob", password_hash="unused")
        db.add_all([role, user, other]); db.flush()
        db.add(m.RolePermission(role_id=role.id, permission_code="ai:chat", permission_type="operation"))
        db.add_all([m.UserRole(user_id=user.id, role_id=role.id), m.UserRole(user_id=other.id, role_id=role.id)])
        session = m.ChatSession(owner_id=user.id, title="test")
        db.add(session); db.commit()
        actor, sid, other_id = user.id, session.id, other.id
    def add(content="归档延期需工程负责人审批。", title="工程归档流程", granted=True, status="published", vector=True):
        with factory() as db:
            unit = m.KnowledgeUnit(unit_code=uuid4().hex, title=title, content=content, creator_id=actor, status=status)
            db.add(unit); db.flush()
            version = m.KnowledgeVersion(unit_id=unit.id, version_number=1, creator_id=actor,
                                         content=content, status="ready")
            db.add(version); db.flush()
            unit.active_version_id = version.id
            chunk = m.KnowledgeChunk(unit_id=unit.id, version_id=version.id, chunk_index=0,
                                     content=content, position_json={"page": 2})
            db.add(chunk); db.flush()
            chunk.vector_id = chunk.id + ":" + uuid4().hex if vector else None
            if granted:
                db.add(m.UnitPermission(unit_id=unit.id, target_type="user", target_id=actor))
            db.commit()
            return {"unit_id": unit.id, "version_id": version.id, "chunk_id": chunk.id,
                    "vector_id": chunk.vector_id, "content": content, "title": title}
    yield SimpleNamespace(factory=factory, actor=actor, sid=sid, other=other_id, add=add, engine=engine)
    engine.dispose()


class Models:
    def __init__(self):
        self.payloads = []
        self.last_usage = {}
        self.fail = set()
        self.score = .95
        self.generation_hook = None
        self.rerank_hook = None
        self.answer = "延期需工程负责人审批。[1]"

    async def embed(self, texts):
        self.payloads.append(("embedding", texts))
        if "embedding" in self.fail:
            raise OSError("fake offline")
        self.last_usage["embedding"] = {"known": True, "total_tokens": 7}
        return [[.1, .2] for _ in texts]

    async def rerank(self, query, texts, limit):
        self.payloads.append(("rerank", texts))
        if self.rerank_hook:
            await self.rerank_hook()
        if "rerank" in self.fail:
            raise OSError("fake offline")
        self.last_usage["rerank"] = {"known": False}
        return [{"index": i, "score": self.score} for i in range(min(limit, len(texts)))]

    async def complete(self, messages, max_tokens, stage):
        self.payloads.append((stage, messages))
        if stage in self.fail:
            raise OSError("fake offline")
        self.last_usage[stage] = {"known": True, "prompt_tokens": 10, "completion_tokens": 3}
        return "工程归档延期怎么审批？" if stage == "rewrite" else "假设不可信文本"

    async def generate(self, messages, max_tokens, on_delta):
        self.payloads.append(("generation", messages))
        if self.generation_hook:
            await self.generation_hook(on_delta)
        if "generation" in self.fail:
            await on_delta("部分尚未完成")
            raise OSError("fake provider disconnect")
        await on_delta(self.answer)
        self.last_usage["generation"] = {"known": True, "prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}
        return self.answer


class Recall:
    def __init__(self, documents=()):
        self.documents = list(documents)
        self.calls = []
        self.forge = False
        self.fail = False

    async def search(self, vector, vector_ids, limit):
        self.calls.append((list(vector_ids), limit))
        if self.fail:
            raise OSError("fake milvus offline")
        selected = [d for d in self.documents if d["vector_id"] in vector_ids]
        return [{"id": d["vector_id"], "distance": .85, "entity": {
            key: ("FORGED VECTOR SECRET" if self.forge and key == "content" else d[key])
            for key in ("vector_id", "unit_id", "version_id", "chunk_id", "content")}} for d in selected[:limit]]


def run(corpus, models=None, recall=None, config=Settings, **kwargs):
    return asyncio.run(RagPipeline(corpus.factory, models or Models(), recall or Recall(), config).run(
        corpus.actor, corpus.sid, "工程归档延期怎么审批？", **kwargs))


def test_general_question_sources_usage_and_denied_never_in_models(corpus):
    allowed = corpus.add()
    denied = corpus.add("归档延期机密审批代码 DENIED_MARKER_37。", title="机密审批标题", granted=False)
    models, recall = Models(), Recall([denied, allowed])
    result = run(corpus, models, recall)
    assert result.status == "completed" and result.sources[0]["chunk_id"] == allowed["chunk_id"]
    assert result.sources[0]["position"] == {"page": 2}
    assert result.permission_hint["denied_count"] == 1
    assert denied["unit_id"] in result.metrics["unauthorized_unit_ids"]
    assert "DENIED_MARKER" not in str(models.payloads)
    assert any(allowed["vector_id"] in ids and denied["vector_id"] not in ids for ids, _ in recall.calls)
    assert not any(allowed["vector_id"] in ids and denied["vector_id"] in ids for ids, _ in recall.calls)
    assert "机密" not in str(result.permission_hint)
    assert result.usage["embedding"][0]["known"] and result.usage["generation"][0]["total_tokens"] == 28
    assert result.usage["rerank"][0]["known"] is False


def test_all_denied_does_not_rerank_or_generate(corpus):
    denied = corpus.add(granted=False)
    models = Models()
    result = run(corpus, models, Recall([denied]))
    assert result.status == "restricted" and result.sources == []
    assert not any(stage in {"generation", "rerank"} for stage, _ in models.payloads)
    assert denied["title"] not in result.answer


def test_no_match_and_low_confidence_are_normal(corpus):
    assert run(corpus).status == "no_match"
    corpus.add()
    models = Models(); models.score = .01
    result = run(corpus, models)
    assert result.status == "low_confidence" and result.sources == []
    assert not any(stage == "generation" for stage, _ in models.payloads)


@pytest.mark.parametrize("status", ["draft", "disabled", "deleted"])
def test_unpublished_author_cannot_supply_model_evidence(corpus, status):
    document = corpus.add(status=status)
    models = Models()
    result = run(corpus, models, Recall([document]))
    assert result.status == "no_match"
    assert not any(stage in {"generation", "rerank"} for stage, _ in models.payloads)


def test_forged_vector_content_never_trusted_and_lexical_remains(corpus):
    document = corpus.add()
    recall = Recall([document]); recall.forge = True
    models = Models()
    result = run(corpus, models, recall)
    assert result.status == "completed" and result.metrics["invalid_vector_count"] >= 1
    assert "FORGED" not in str(models.payloads)
    assert document["content"] in str(models.payloads)


def test_old_vector_winning_attempt_and_active_version_checked(corpus):
    old = corpus.add()
    with corpus.factory() as db:
        unit = db.get(m.KnowledgeUnit, old["unit_id"])
        new = m.KnowledgeVersion(unit_id=unit.id, creator_id=corpus.actor, version_number=2,
                                content="当前版本归档延期需要新的审批。", status="ready")
        db.add(new); db.flush(); unit.active_version_id = new.id
        db.commit()
    result = run(corpus, recall=Recall([old]))
    assert result.status == "no_match" and result.sources == []


@pytest.mark.parametrize("action", ["grant", "version", "user", "operation", "token", "session"])
def test_revocation_after_rerank_prevents_generation(corpus, action):
    document = corpus.add()
    models = Models()
    async def revoke():
        with corpus.factory() as db:
            if action == "grant":
                db.execute(delete(m.UnitPermission).where(m.UnitPermission.unit_id == document["unit_id"]))
            elif action == "version":
                db.get(m.KnowledgeUnit, document["unit_id"]).status = "disabled"
            elif action == "user":
                db.get(m.User, corpus.actor).status = "disabled"
            elif action == "operation":
                db.execute(delete(m.RolePermission))
            elif action == "token":
                db.get(m.User, corpus.actor).token_version += 1
            else:
                db.get(m.ChatSession, corpus.sid).status = "deleted"
            db.commit()
    models.rerank_hook = revoke
    result = run(corpus, models, Recall([document]), token_version=1)
    assert result.status == "restricted" and result.answer == "" and result.sources == []
    assert result.permission_hint["code"] == "permission_changed"
    assert not any(stage == "generation" for stage, _ in models.payloads)


def test_stream_revocation_stops_new_delta_and_discards_result(corpus):
    document = corpus.add()
    models, received = Models(), []
    async def during_generation(on_delta):
        await on_delta("已授权第一段")
        with corpus.factory() as db:
            db.execute(delete(m.UnitPermission).where(m.UnitPermission.unit_id == document["unit_id"]))
            db.commit()
        await on_delta("撤权后机密段")
    async def delta(text):
        received.append(text)
    models.generation_hook = during_generation
    result = run(corpus, models, Recall([document]), on_delta=delta)
    assert received == ["已授权第一段"]
    assert result.status == "restricted" and not result.answer and not result.sources
    assert result.usage["generation"][0]["known"] is False


def test_multiround_revalidated_before_model(corpus):
    source = corpus.add(granted=False)
    models = Models()
    async def history():
        return [{"role": "assistant", "content": "REVOKED_HISTORY_SECRET", "sources": [source]}]
    result = run(corpus, models, history_loader=history)
    assert result.status == "restricted" and not models.payloads


def test_safe_multiround_rewrite_failure_uses_original(corpus):
    source = corpus.add()
    models = Models(); models.fail.add("rewrite")
    async def history():
        return [{"role": "assistant", "content": "工程归档", "sources": [source]}]
    result = run(corpus, models, history_loader=history)
    assert result.status == "completed" and result.rewritten_question == "工程归档延期怎么审批？"
    assert any(d["node"] == "rewrite" for d in result.degradations)


@pytest.mark.parametrize("failure", ["embedding", "rerank", "dense"])
def test_partial_retrieval_failure_honest_degradation(corpus, failure):
    source = corpus.add()
    models, recall = Models(), Recall([source])
    if failure == "dense": recall.fail = True
    else: models.fail.add(failure)
    result = run(corpus, models, recall)
    assert result.status == "completed" and result.degradations
    assert source["chunk_id"] == result.sources[0]["chunk_id"]


def test_dense_bounded_widening_when_initial_candidate_invalid(corpus):
    sources = [corpus.add(content="数据规范事项" + str(i), title="数据规范") for i in range(2)]
    class WidenRecall(Recall):
        async def search(self, vector, vector_ids, limit):
            hits = await super().search(vector, vector_ids, limit)
            if hits: hits[0]["entity"]["content"] = "stale attempt"
            return hits
    recall = WidenRecall(sources)
    result = run(corpus, recall=recall)
    assert [limit for _, limit in recall.calls] == [1, 2]
    assert result.metrics["invalid_vector_count"] == 2
    assert result.status == "completed"


def test_invalid_or_missing_generation_citations_fail(corpus):
    corpus.add()
    for answer in ["随意回答没有引用", "错误引用[99]"]:
        models = Models(); models.answer = answer
        result = run(corpus, models)
        assert result.status == "error" and not result.answer and not result.sources
        assert result.degradations[-1]["reason"] == "missing_or_invalid_citations"


def test_actual_cited_sources_distinct_from_context(corpus):
    for i in range(2): corpus.add(content="工程归档延期流程" + str(i))
    result = run(corpus)
    assert len(result.metrics["context_sources"]) == 2 and len(result.sources) == 1


def test_optional_hyde_never_cited_and_web_safe(corpus):
    document = corpus.add()
    class OptionalSettings(Settings):
        hyde_enabled = True
        web_enabled = True
    models = Models()
    result = run(corpus, models, Recall([document]), config=OptionalSettings)
    assert result.status == "completed" and "假设" not in str(result.sources)
    assert "hyde" in result.usage and len(result.usage["embedding"]) == 2
    assert "假设不可信文本" not in str([p for stage, p in models.payloads if stage == "generation"])
    assert {"node": "web", "reason": "external_search_failed"} in result.degradations


def test_cross_user_session_rejected_before_models(corpus):
    models = Models()
    result = asyncio.run(RagPipeline(corpus.factory, models, Recall(), Settings).run(corpus.other, corpus.sid, "流程？"))
    assert result.status == "restricted" and not models.payloads


def test_rrf_stable_ids_empty_duplicates_and_deterministic_ties():
    def doc(key): return {"chunk_id": key, "unit_id": "u", "version_id": "v"}
    result = reciprocal_rank_fusion([[doc(""), doc("a"), doc("a"), doc("b")], [doc("b"), doc("a")]])
    assert len(result) == 2 and result[0]["chunk_id"] == "a"
    assert reciprocal_rank_fusion([[], []]) == []
    assert reciprocal_rank_fusion([[doc("b")], [doc("a")]])[0]["chunk_id"] == "a"


def test_lexical_chinese_and_empty_candidates():
    assert lexical_rank("归档流程", []) == []
    assert lexical_rank("归档流程", [{"title": "归档规范", "content": "项目归档流程", "chunk_id": "a"}])[0]["score"] > .1


def test_cancellation_propagates_and_snapshot_preserves_actual_usage(corpus):
    document = corpus.add()
    models = Models()
    async def cancelled(on_delta):
        raise asyncio.CancelledError()
    models.generation_hook = cancelled
    pipeline = RagPipeline(corpus.factory, models, Recall([document]), Settings)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline.run(corpus.actor, corpus.sid, "归档延期？"))
    snapshot = pipeline.snapshot()
    assert snapshot["metrics"]["authorized_unit_ids"] == [document["unit_id"]]
    assert snapshot["usage"]["embedding"][0]["total_tokens"] == 7
    assert snapshot["usage"]["generation"][0]["status"] == "cancelled"


def test_actual_task_cancellation_stops_provider(corpus):
    document = corpus.add()
    models, started, closed = Models(), asyncio.Event(), []
    async def active(on_delta):
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            closed.append(True)
    models.generation_hook = active
    pipeline = RagPipeline(corpus.factory, models, Recall([document]), Settings)
    async def scenario():
        task = asyncio.create_task(pipeline.run(corpus.actor, corpus.sid, "归档延期？"))
        await asyncio.wait_for(started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert closed == [True]
    assert pipeline.snapshot()["usage"]["generation"][0]["status"] == "cancelled"


def test_enabled_web_distinct_and_original_question_only(corpus):
    document = corpus.add()
    class WebModels(Models):
        async def web_search(self, question, limit):
            self.payloads.append(("web", question))
            return [{"source_type": "external", "title": "公网说明", "snippet": "EXTERNAL_ONLY", "url": "https://example.org"}]
    class WebSettings(Settings):
        web_enabled = True
    models, progress = WebModels(), []
    async def history():
        return [{"role": "assistant", "content": "私人历史", "sources": [document]}]
    async def on_progress(data): progress.append(data)
    result = run(corpus, models, Recall([document]), config=WebSettings, history_loader=history, on_progress=on_progress)
    assert models.payloads[[stage for stage, _ in models.payloads].index("web")][1] == "工程归档延期怎么审批？"
    assert result.metrics["external_sources"][0]["source_type"] == "external"
    assert "EXTERNAL_ONLY" not in str([p for stage, p in models.payloads if stage == "generation"])
    assert any(item.get("external_sources") for item in progress)


def test_long_chunk_lexical_matches_later_text(corpus):
    corpus.add(content="普通说明段落" * 80 + "工程归档延期流程", vector=False, title="普通说明")
    models = Models(); models.fail.add("embedding")
    assert run(corpus, models).status == "completed"


@pytest.mark.parametrize("wrong_key", ["id", "vector_id", "unit_id", "version_id", "chunk_id"])
def test_forged_vector_identity_never_enters_models(corpus, wrong_key):
    source = corpus.add(title="向量资料", content="向量证据正文")
    class WrongIdentity(Recall):
        async def search(self, vector, vector_ids, limit):
            hits = await super().search(vector, vector_ids, limit)
            if hits:
                if wrong_key == "id": hits[0]["id"] = "failed_attempt"
                else: hits[0]["entity"][wrong_key] = "forged_identity"
            return hits
    models = Models()
    result = run(corpus, models, WrongIdentity([source]))
    assert result.status == "no_match" and result.metrics["invalid_vector_count"] == 1
    assert not any(stage in {"rerank", "generation"} for stage, _ in models.payloads)


def test_history_all_context_provenance_even_uncited(corpus):
    first, second = corpus.add(), corpus.add()
    async def history():
        return [{"role": "user", "content": "上一轮问题", "sources": [second]},
                {"role": "assistant", "content": "上一轮答案", "sources": [second]}]
    result = run(corpus, history_loader=history)
    dependencies = result.metrics["authorization_dependencies"]
    assert {d["unit_id"] for d in dependencies} == {first["unit_id"], second["unit_id"]}
    assert len(result.sources) == 1 and len(result.metrics["context_sources"]) == 2


def test_semantic_only_denied_probe_counts_without_model_evidence(corpus):
    hidden = corpus.add(title="受控保密材料", content="RESTRICTED_SEMANTIC_PROBE", granted=False)
    models = Models()
    result = run(corpus, models, Recall([hidden]))
    assert result.status == "restricted" and result.permission_hint["denied_count"] == 1
    assert result.metrics["unauthorized_unit_ids"] == [hidden["unit_id"]]
    assert "RESTRICTED_SEMANTIC_PROBE" not in str(models.payloads)
    assert "受控" not in result.answer


def test_milvus_named_primary_key_response_shape(corpus):
    source = corpus.add(title="向量资料", content="语义证据正文")
    class NamedPrimary(Recall):
        async def search(self, vector, vector_ids, limit):
            hits = await super().search(vector, vector_ids, limit)
            for hit in hits: hit["vector_id"] = hit.pop("id")
            return hits
    result = run(corpus, recall=NamedPrimary([source]))
    assert result.status == "completed" and result.metrics["invalid_vector_count"] == 0
    assert result.metrics["dense_candidate_chunk_ids"] == [source["chunk_id"]]
    assert result.metrics["lexical_candidate_chunk_ids"] == []
