"""Cancellation-aware remote model adapters using the existing provider contracts.

Usage is copied from provider responses. Missing usage stays unknown; character
counts and token estimates are never reported as billed model usage.
"""
import json
import math
from urllib.parse import urlsplit

import httpx

from atguigu.config.config import EmbeddingConfig, LLMConfig, RerankConfig, RuntimeConfig


def provider_usage(payload):
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if not isinstance(usage, dict):
        return {"known": False}
    clean = {k: v for k, v in usage.items() if isinstance(v, (int, dict)) and not isinstance(v, bool)}
    return {"known": bool(clean), **clean}


class RemoteRagAdapters:
    """HTTP clients are per call so cancellation reliably closes active streams."""

    def __init__(self):
        self.last_usage = {}

    async def _post(self, url, key, payload):
        if not url or not key:
            raise RuntimeError("模型服务尚未配置")
        async with httpx.AsyncClient(timeout=RuntimeConfig.model_timeout) as client:
            response = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json=payload)
            response.raise_for_status()
            return response.json()

    async def web_search(self, question, limit=5):
        from atguigu.config.config import McpConfig
        if not McpConfig.mcp_base_url or not McpConfig.api_key:
            raise RuntimeError("联网搜索服务尚未配置")
        from atguigu.query_process.nodes.node_web_search_mcp import NodeWebSearchMcp
        response = await NodeWebSearchMcp().mcp_run(question, limit)
        pages = []
        for block in response.content:
            if getattr(block, "text", None):
                parsed = json.loads(block.text)
                if isinstance(parsed.get("pages"), list):
                    pages.extend(parsed["pages"])
        external = []
        for page in pages[:limit]:
            title, snippet, url = page.get("title"), page.get("snippet"), page.get("url")
            if not all(isinstance(v, str) for v in (title, snippet, url)):
                continue
            parts = urlsplit(url)
            if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
                continue
            external.append({"source_type": "external", "title": title[:255], "snippet": snippet[:500], "url": url,
                             "label": "外部搜索结果，不作为内部制度依据"})
        return external

    async def embed(self, texts):
        body = await self._post(f"{EmbeddingConfig.embedding_base_url}/embeddings",
                                EmbeddingConfig.embedding_api_key,
                                {"model": EmbeddingConfig.model, "input": texts,
                                 "dimensions": EmbeddingConfig.dimensions, "encoding_format": "float"})
        self.last_usage["embedding"] = provider_usage(body)
        data = body.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError("向量数量无效")
        vectors = [None] * len(texts)
        for item in data:
            index, vector = item.get("index"), item.get("embedding")
            if type(index) is not int or not 0 <= index < len(texts) or vectors[index] is not None:
                raise ValueError("向量索引无效")
            if not isinstance(vector, list) or len(vector) != EmbeddingConfig.dimensions:
                raise ValueError("向量维度无效")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
                raise ValueError("向量数值无效")
            vectors[index] = vector
        return vectors

    async def rerank(self, question, documents, limit):
        body = await self._post(f"{RerankConfig.rerank_base_url}/rerank", RerankConfig.rerank_api_key,
                                {"model": RerankConfig.model, "query": question, "documents": documents,
                                 "top_n": min(limit, len(documents)), "return_documents": False})
        self.last_usage["rerank"] = provider_usage(body)
        results = body.get("results")
        if not isinstance(results, list) or len(results) > min(limit, len(documents)):
            raise ValueError("重排结果无效")
        seen, ranked = set(), []
        for item in results:
            index, score = item.get("index"), item.get("relevance_score")
            if type(index) is not int or not 0 <= index < len(documents) or index in seen:
                raise ValueError("重排索引无效")
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError("重排分数无效")
            seen.add(index)
            ranked.append({"index": index, "score": float(score)})
        return sorted(ranked, key=lambda r: (-r["score"], r["index"]))

    async def complete(self, messages, max_tokens, stage):
        body = await self._post(f"{LLMConfig.openai_api_base.rstrip('/')}/chat/completions",
                                LLMConfig.openai_api_key,
                                {"model": LLMConfig.llm_default_model, "messages": messages,
                                 "temperature": LLMConfig.llm_default_temperature, "max_tokens": max_tokens})
        self.last_usage[stage] = provider_usage(body)
        content = body["choices"][0]["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("模型返回空文本")
        return content.strip()

    async def generate(self, messages, max_tokens, on_delta):
        if not LLMConfig.openai_api_base or not LLMConfig.openai_api_key:
            raise RuntimeError("生成模型服务尚未配置")
        payload = {"model": LLMConfig.llm_default_model, "messages": messages,
                   "temperature": LLMConfig.llm_default_temperature, "max_tokens": max_tokens,
                   "stream": True, "stream_options": {"include_usage": True}}
        self.last_usage["generation"] = {"known": False}
        answer = []
        async with httpx.AsyncClient(timeout=RuntimeConfig.model_timeout) as client:
            # Some OpenAI-compatible services reject stream_options before starting.
            # Retry only that explicit compatibility rejection, never a partial stream.
            for attempt in range(2):
                async with client.stream("POST", f"{LLMConfig.openai_api_base.rstrip('/')}/chat/completions",
                                         headers={"Authorization": f"Bearer {LLMConfig.openai_api_key}"},
                                         json=payload) as response:
                    if response.status_code in {400, 422} and attempt == 0:
                        error = (await response.aread()).decode("utf-8", errors="replace")
                        if "stream_options" in error:
                            payload.pop("stream_options", None)
                            continue
                    response.raise_for_status()
                    finished = False
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            finished = True
                            break
                        body = json.loads(data)
                        if "error" in body:
                            raise RuntimeError("模型流式返回错误")
                        if provider_usage(body)["known"]:
                            self.last_usage["generation"] = provider_usage(body)
                        for choice in body.get("choices", []):
                            if choice.get("finish_reason"):
                                finished = True
                            delta = choice.get("delta", {}).get("content")
                            if isinstance(delta, str) and delta:
                                # The caller performs a fresh authorization check here.
                                await on_delta(delta)
                                answer.append(delta)
                    if not finished:
                        raise RuntimeError("模型流式响应意外中断")
                    break
        if not answer:
            raise ValueError("生成模型返回空答案")
        return "".join(answer)
