"""Version-aware dense vectors isolated from the original stage-one collections."""
import json
import threading

from atguigu.config.config import EmbeddingConfig, ImportConfig, RuntimeConfig
from atguigu.tool.milvus_client_tool import get_milvus_client

_schema_lock = threading.Lock()


class KnowledgeIndex:
    def __init__(self):
        ImportConfig.validate()
        self.client = get_milvus_client()
        self.collection = ImportConfig.collection

    def ensure_collection(self):
        from pymilvus import DataType
        with _schema_lock:
            if not self.client.has_collection(self.collection):
                schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
                schema.add_field("vector_id", DataType.VARCHAR, is_primary=True, max_length=100)
                for name in ["unit_id", "version_id", "chunk_id"]:
                    schema.add_field(name, DataType.VARCHAR, max_length=36)
                schema.add_field("attempt_token", DataType.VARCHAR, max_length=36)
                schema.add_field("chunk_index", DataType.INT64)
                schema.add_field("content", DataType.VARCHAR, max_length=65535)
                schema.add_field("position", DataType.JSON)
                schema.add_field("dense_vector", DataType.FLOAT_VECTOR, dim=EmbeddingConfig.dimensions)
                params = self.client.prepare_index_params()
                params.add_index(field_name="dense_vector", index_type="AUTOINDEX", metric_type="COSINE")
                try:
                    self.client.create_collection(self.collection, schema=schema, index_params=params,
                                                  consistency_level="Strong", timeout=RuntimeConfig.model_timeout)
                except Exception:
                    if not self.client.has_collection(self.collection):
                        raise
            fields = self.client.describe_collection(self.collection)["fields"]
            by_name = {f["name"]: f for f in fields}
            if not {"vector_id", "unit_id", "version_id", "chunk_id", "attempt_token", "dense_vector"} <= by_name.keys():
                raise ValueError("知识索引集合 schema 不兼容，请指定新的独立集合")
            if int(by_name["dense_vector"].get("params", {}).get("dim", 0)) != EmbeddingConfig.dimensions:
                raise ValueError("知识索引集合维度不匹配，请指定新的独立集合")

    def upsert(self, unit_id, version_id, token, chunks, vectors):
        # Each lease writes its own vector IDs. An expired process cannot overwrite the winner.
        rows = [{"vector_id": f"{c['id']}:{token}", "unit_id": unit_id, "version_id": version_id,
                 "chunk_id": c["id"], "attempt_token": token, "chunk_index": c["chunk_index"],
                 "content": c["content"], "position": c["position_json"], "dense_vector": v}
                for c, v in zip(chunks, vectors, strict=True)]
        result = self.client.upsert(self.collection, rows, timeout=RuntimeConfig.model_timeout)
        if result.get("upsert_count") != len(rows):
            raise RuntimeError("Milvus 写入数量与切片数量不一致")

    def verify(self, vector_ids):
        self.client.flush(self.collection, timeout=RuntimeConfig.model_timeout)
        for start in range(0, len(vector_ids), 100):
            ids = vector_ids[start:start + 100]
            rows = self.client.query(self.collection, filter="vector_id in " + json.dumps(ids),
                                     output_fields=["vector_id"], consistency_level="Strong",
                                     timeout=RuntimeConfig.model_timeout)
            if {r["vector_id"] for r in rows} != set(ids):
                raise RuntimeError("Milvus 索引校验未通过")


def get_index():
    return KnowledgeIndex()
