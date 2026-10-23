"""Remote dense embeddings shared by document imports and all retrieval paths."""
import math
from typing import List

import httpx

from atguigu.config.config import EmbeddingConfig, RuntimeConfig


def get_embeddings(texts: List[str]):
    if not texts:
        return {"dense": []}
    if any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("向量化输入必须是非空文本")
    if not (EmbeddingConfig.embedding_base_url and EmbeddingConfig.embedding_api_key):
        raise RuntimeError("请配置 EMBEDDING_BASE_URL/API_KEY，或共享 RERANK_BASE_URL/API_KEY")

    response = httpx.post(
        f"{EmbeddingConfig.embedding_base_url}/embeddings",
        headers={"Authorization": f"Bearer {EmbeddingConfig.embedding_api_key}"},
        json={
            "model": EmbeddingConfig.model,
            "input": texts,
            "dimensions": EmbeddingConfig.dimensions,
            "encoding_format": "float",
        },
        timeout=RuntimeConfig.model_timeout,
    )
    response.raise_for_status()
    data = response.json().get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise ValueError("Embedding 接口返回的向量数量与输入不一致")

    dense = [None] * len(texts)
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Embedding 接口返回格式无效")
        index, vector = item.get("index"), item.get("embedding")
        if type(index) is not int or not 0 <= index < len(texts) or dense[index] is not None:
            raise ValueError("Embedding 接口返回的索引无效或重复")
        if not isinstance(vector, list) or len(vector) != EmbeddingConfig.dimensions:
            raise ValueError("Embedding 接口返回维度与 EMBEDDING_DIMENSIONS 不一致")
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in vector):
            raise ValueError("Embedding 接口返回了无效的向量数值")
        dense[index] = [float(value) for value in vector]
    return {"dense": dense}
