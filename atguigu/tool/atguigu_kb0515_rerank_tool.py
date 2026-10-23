"""EMRank /v1/rerank adapter, returning the graph's index/score format."""
import math

import httpx

from atguigu.config.config import RerankConfig, RuntimeConfig


def text_rerank(query, texts, limit=10):
    if not texts:
        return []
    if not query or limit < 1:
        raise ValueError("重排序必须提供问题，且 limit 必须大于 0")
    if not (RerankConfig.rerank_base_url and RerankConfig.rerank_api_key):
        raise RuntimeError("请配置 RERANK_BASE_URL 和 RERANK_API_KEY")

    response = httpx.post(
        f"{RerankConfig.rerank_base_url}/rerank",
        headers={"Authorization": f"Bearer {RerankConfig.rerank_api_key}"},
        json={
            "model": RerankConfig.model,
            "query": query,
            "documents": texts,
            "top_n": min(limit, len(texts)),
            "return_documents": False,
        },
        timeout=RuntimeConfig.model_timeout,
    )
    response.raise_for_status()
    results = response.json().get("results")
    if not isinstance(results, list) or not results or len(results) > min(limit, len(texts)):
        raise ValueError("Rerank 接口返回结果无效")
    ranked, seen = [], set()
    for item in results:
        if not isinstance(item, dict):
            raise ValueError("Rerank 接口返回格式无效")
        index, score = item.get("index"), item.get("relevance_score")
        if type(index) is not int or not 0 <= index < len(texts) or index in seen:
            raise ValueError("Rerank 接口返回的文档索引无效或重复")
        if type(score) not in (int, float) or not math.isfinite(score):
            raise ValueError("Rerank 接口返回的相关性分数无效")
        seen.add(index)
        ranked.append({"index": index, "score": float(score)})
    return sorted(ranked, key=lambda item: item["score"], reverse=True)
