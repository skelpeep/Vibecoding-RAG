"""Remote HTTP contracts with explicit fake transport; no live-provider claim."""
import asyncio
import json

import httpx
import pytest

from atguigu.business.rag_adapters import RemoteRagAdapters, provider_usage
from atguigu.config.config import EmbeddingConfig, LLMConfig, RerankConfig


@pytest.fixture
def providers(monkeypatch):
    monkeypatch.setattr(LLMConfig, "openai_api_base", "https://llm.invalid/v1")
    monkeypatch.setattr(LLMConfig, "openai_api_key", "transport-test")
    monkeypatch.setattr(LLMConfig, "llm_default_model", "fake-llm")
    monkeypatch.setattr(EmbeddingConfig, "embedding_base_url", "https://embedding.invalid/v1")
    monkeypatch.setattr(EmbeddingConfig, "embedding_api_key", "transport-test")
    monkeypatch.setattr(EmbeddingConfig, "dimensions", 2)
    monkeypatch.setattr(RerankConfig, "rerank_base_url", "https://rerank.invalid/v1")
    monkeypatch.setattr(RerankConfig, "rerank_api_key", "transport-test")


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


def event(data):
    return "data: " + json.dumps(data) + "\n\n"


def test_real_sse_delta_usage_and_payload(monkeypatch, providers):
    payloads, received = [], []
    def handler(request):
        payloads.append(json.loads(request.content))
        body = event({"choices": [{"delta": {"content": "第一段"}}]})
        body += event({"choices": [{"delta": {"content": "第二段[1]"}, "finish_reason": "stop"}]})
        body += event({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}})
        return httpx.Response(200, text=body + "data: [DONE]\n\n")
    transport(monkeypatch, handler)
    adapter = RemoteRagAdapters()
    async def delta(text): received.append(text)
    result = asyncio.run(adapter.generate([{"role": "user", "content": "问题"}], 500, delta))
    assert received == ["第一段", "第二段[1]"] and result == "第一段第二段[1]"
    assert payloads[0]["stream_options"] == {"include_usage": True}
    assert payloads[0]["stream"] is True
    assert adapter.last_usage["generation"]["total_tokens"] == 17


def test_stream_options_explicit_fallback_and_unknown_usage(monkeypatch, providers):
    payloads = []
    def handler(request):
        body = json.loads(request.content); payloads.append(body)
        if "stream_options" in body:
            return httpx.Response(400, json={"error": "unsupported stream_options"})
        return httpx.Response(200, text=event({"choices": [{"delta": {"content": "回答[1]"}}]}) + "data: [DONE]\n\n")
    transport(monkeypatch, handler)
    adapter = RemoteRagAdapters()
    async def delta(text): pass
    assert asyncio.run(adapter.generate([], 300, delta)) == "回答[1]"
    assert len(payloads) == 2 and "stream_options" not in payloads[1]
    assert adapter.last_usage["generation"] == {"known": False}


def test_noncompatibility_failure_not_retried(monkeypatch, providers):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(400, json={"error": "bad model"})
    transport(monkeypatch, handler)
    async def delta(text): pass
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(RemoteRagAdapters().generate([], 300, delta))
    assert len(calls) == 1


def test_stream_truncation_after_partial_delta_is_error(monkeypatch, providers):
    transport(monkeypatch, lambda request: httpx.Response(200, text=event({"choices": [{"delta": {"content": "部分"}}]})))
    received = []
    async def delta(text): received.append(text)
    with pytest.raises(RuntimeError, match="中断"):
        asyncio.run(RemoteRagAdapters().generate([], 300, delta))
    assert received == ["部分"]


class WaitingStream(httpx.AsyncByteStream):
    def __init__(self):
        self.waiting = asyncio.Event()
        self.closed = False
    async def __aiter__(self):
        yield event({"choices": [{"delta": {"content": "首段"}}]}).encode()
        self.waiting.set()
        await asyncio.Event().wait()
    async def aclose(self): self.closed = True


def test_cancellation_closes_real_async_stream(monkeypatch, providers):
    stream = WaitingStream()
    transport(monkeypatch, lambda request: httpx.Response(200, stream=stream))
    async def delta(text): pass
    async def run():
        task = asyncio.create_task(RemoteRagAdapters().generate([], 300, delta))
        await asyncio.wait_for(stream.waiting.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(run())
    assert stream.closed


def test_usage_embedding_and_rerank_contract_validation(monkeypatch, providers):
    def handler(request):
        if request.url.path.endswith("embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1., 2.]}], "usage": {"total_tokens": 6}})
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": .9}], "usage": {"total_tokens": 8}})
    transport(monkeypatch, handler)
    adapter = RemoteRagAdapters()
    assert asyncio.run(adapter.embed(["正文"])) == [[1., 2.]]
    assert asyncio.run(adapter.rerank("问题", ["正文"], 1)) == [{"index": 0, "score": .9}]
    assert adapter.last_usage["embedding"]["total_tokens"] == 6
    assert adapter.last_usage["rerank"]["total_tokens"] == 8
    assert provider_usage({}) == {"known": False}


@pytest.mark.parametrize("results", [[{"index": 99, "relevance_score": .2}], [{"index": 0, "relevance_score": float("nan")}],
    [{"index": 0, "relevance_score": .9}, {"index": 0, "relevance_score": .8}]])
def test_untrusted_provider_rerank_indexes_rejected(monkeypatch, providers, results):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"results": results}))
    with pytest.raises(ValueError): asyncio.run(RemoteRagAdapters().rerank("问题", ["正文", "正文2"], 2))
