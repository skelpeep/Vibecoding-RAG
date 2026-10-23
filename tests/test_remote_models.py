"""Protocol and graph regressions; mocked responses do not claim live inference."""
import runpy
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from atguigu.config.config import EmbeddingConfig, LLMConfig, RuntimeConfig
from atguigu.tool import embedding_client_tool, milvus_client_tool
from atguigu.tool.atguigu_kb0515_rerank_tool import text_rerank


@pytest.fixture
def remote(monkeypatch):
    monkeypatch.setattr(EmbeddingConfig, "embedding_base_url", "https://gateway.example/v1")
    monkeypatch.setattr(EmbeddingConfig, "embedding_api_key", "embedding-test-key")
    monkeypatch.setattr(EmbeddingConfig, "dimensions", 2)
    post = Mock()
    monkeypatch.setattr(httpx, "post", post)
    return post


def response(body, status=200):
    return httpx.Response(status, json=body, request=httpx.Request("POST", "https://gateway.example/v1/embeddings"))


def test_embedding_orders_vectors_by_input_and_uses_remote_config(remote):
    remote.return_value = response({"data": [
        {"index": 1, "embedding": [0.2, 0.9]},
        {"index": 0, "embedding": [0.8, 0.1]},
    ]})
    assert embedding_client_tool.get_embeddings(["first", "second"]) == {"dense": [[0.8, 0.1], [0.2, 0.9]]}
    args, kwargs = remote.call_args
    assert args == ("https://gateway.example/v1/embeddings",)
    assert kwargs["headers"]["Authorization"] == "Bearer embedding-test-key"
    assert kwargs["json"]["model"] == "Qwen/Qwen3-Embedding-8B"
    assert kwargs["json"]["input"] == ["first", "second"]
    assert kwargs["json"]["dimensions"] == 2
    assert kwargs["timeout"] == RuntimeConfig.model_timeout


@pytest.mark.parametrize("data", [
    [],
    [{"index": 0, "embedding": [1]}],
    [{"index": 1, "embedding": [1, 0]}],
    [{"index": 0, "embedding": [float("nan"), 0]}],
])
def test_embedding_rejects_invalid_vectors_before_storage(remote, data):
    remote.return_value = Mock(json=Mock(return_value={"data": data}))
    with pytest.raises(ValueError):
        embedding_client_tool.get_embeddings(["document"])


def test_auth_failure_does_not_fall_back_to_local_model(remote):
    remote.return_value = response({"error": "unauthorized"}, status=401)
    with pytest.raises(httpx.HTTPStatusError):
        embedding_client_tool.get_embeddings(["document"])
    assert remote.call_count == 1


def test_empty_embedding_needs_no_remote_request(remote):
    assert embedding_client_tool.get_embeddings([]) == {"dense": []}
    remote.assert_not_called()


def test_embedding_reuses_rerank_config_and_vision_has_independent_credentials(monkeypatch):
    from atguigu.config import config
    for name, value in {
        "OPENAI_API_BASE": "https://chat.example/v1", "OPENAI_API_KEY": "chat-key",
        "VL_BASE_URL": "https://vision.example/v1/", "VL_API_KEY": "vision-key",
        "RERANK_BASE_URL": "https://rerank.example/v1/", "RERANK_API_KEY": "gateway-key",
        "EMBEDDING_BASE_URL": "", "EMBEDDING_API_KEY": "",
        "EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-8B", "EMBEDDING_DIMENSIONS": "4096",
    }.items():
        monkeypatch.setenv(name, value)
    values = runpy.run_path(config.__file__)
    assert values["EmbeddingConfig"].embedding_base_url == "https://rerank.example/v1"
    assert values["EmbeddingConfig"].embedding_api_key == "gateway-key"
    assert values["LLMConfig"].vl_base_url == "https://vision.example/v1"
    assert values["LLMConfig"].vl_api_key == "vision-key"
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://embedding.example/v1")
    monkeypatch.setenv("EMBEDDING_API_KEY", "separate-key")
    monkeypatch.setenv("VL_API_KEY", "")
    values = runpy.run_path(config.__file__)
    assert values["EmbeddingConfig"].embedding_api_key == "separate-key"
    assert values["EmbeddingConfig"].embedding_base_url == "https://embedding.example/v1"
    assert values["LLMConfig"].vl_api_key == ""


def test_vision_uses_its_own_provider(monkeypatch, tmp_path):
    from atguigu.import_process.nodes import node_md_img
    monkeypatch.setattr(LLMConfig, "vl_base_url", "https://vision.example/v1")
    monkeypatch.setattr(LLMConfig, "vl_api_key", "vision-test-key")
    monkeypatch.setattr(LLMConfig, "vl_model", "vision-model")
    init = Mock(return_value=Mock(invoke=Mock(return_value=SimpleNamespace(content="图片摘要"))))
    monkeypatch.setattr(node_md_img, "init_chat_model", init)
    picture = tmp_path / "sample.jpg"
    picture.write_bytes(b"test-image")
    result = node_md_img.NodeMDImg().get_image_with_summary_list([
        {"image_path": str(picture), "pre_text": "before", "post_text": "after"},
    ])
    assert init.call_args.kwargs["base_url"] == "https://vision.example/v1"
    assert init.call_args.kwargs["api_key"] == "vision-test-key"
    assert init.call_args.kwargs["model"] == "vision-model"
    assert result[0]["summary"] == "图片摘要"


def test_vision_missing_key_never_uses_chat_key(monkeypatch):
    from atguigu.import_process.nodes.node_md_img import NodeMDImg
    monkeypatch.setattr(LLMConfig, "vl_api_key", "")
    monkeypatch.setattr(LLMConfig, "openai_api_key", "chat-only-key")
    assert NodeMDImg().get_image_with_summary_list([]) == []
    with pytest.raises(RuntimeError, match="VL_API_KEY"):
        NodeMDImg().get_image_with_summary_list([{"image_path": "unused"}])


def test_rerank_gateway_protocol_and_graph_score_mapping(remote, monkeypatch):
    from atguigu.config.config import RerankConfig
    monkeypatch.setattr(RerankConfig, "rerank_base_url", "https://gateway.example/v1")
    monkeypatch.setattr(RerankConfig, "rerank_api_key", "rerank-test-key")
    remote.return_value = response({"results": [
        {"index": 0, "relevance_score": 0.1}, {"index": 1, "relevance_score": 0.9},
    ]})
    assert text_rerank("question", ["first", "second"], 5) == [
        {"index": 1, "score": 0.9}, {"index": 0, "score": 0.1},
    ]
    args, kwargs = remote.call_args
    assert args == ("https://gateway.example/v1/rerank",)
    assert kwargs["headers"]["Authorization"] == "Bearer rerank-test-key"
    assert kwargs["json"]["top_n"] == 2
    assert kwargs["json"]["model"] == "Qwen/Qwen3-Reranker-8B"


def test_dense_search_preserves_filter_and_result_shape(monkeypatch):
    client = Mock()
    monkeypatch.setattr(EmbeddingConfig, "dimensions", 2)
    monkeypatch.setattr(milvus_client_tool, "get_milvus_client", lambda: client)
    client.describe_collection.return_value = {"fields": [
        {"name": "dense_vector", "params": {"dim": 2}},
    ]}
    client.search.return_value = [[{"entity": {"content": "matched"}, "distance": 0.9}]]
    result = milvus_client_tool.search_dense("documents", [1, 0], expr='item_name in ["device"]')
    assert result[0][0]["entity"]["content"] == "matched"
    assert client.search.call_args.kwargs["filter"] == 'item_name in ["device"]'
    assert client.search.call_args.kwargs["anns_field"] == "dense_vector"
    client.hybrid_search.assert_not_called()


@pytest.mark.parametrize("fields", [
    [{"name": "dense_vector", "params": {"dim": 1024}}],
    [{"name": "dense_vector", "params": {"dim": 4096}}, {"name": "sparse_vector"}],
])
def test_incompatible_existing_collections_are_preserved(fields):
    client = Mock()
    client.describe_collection.return_value = {"fields": fields}
    with pytest.raises(ValueError, match="新集合"):
        milvus_client_tool.validate_dense_collection(client, "existing", 4096)
    client.drop_collection.assert_not_called()
    client.delete.assert_not_called()
    client.insert.assert_not_called()


def test_import_creates_both_schemas_with_remote_dimensions(monkeypatch):
    from atguigu.import_process.nodes import node_import_milvus, node_item_name_recognition
    for module, node_class in [
        (node_import_milvus, node_import_milvus.NodeImportMilvus),
        (node_item_name_recognition, node_item_name_recognition.NodeItemNameRecognition),
    ]:
        client = Mock()
        client.has_collection.return_value = False
        client.create_schema.return_value.add_field.return_value = client.create_schema.return_value
        monkeypatch.setattr(module, "get_milvus_client", lambda: client)
        node_class().create_milvus_collection(4096)
        fields = client.create_schema.return_value.add_field.call_args_list
        dense = next(call.kwargs for call in fields if call.kwargs["field_name"] == "dense_vector")
        assert dense["dim"] == 4096
        assert not any(call.kwargs["field_name"] == "sparse_vector" for call in fields)


def test_all_retrieval_nodes_accept_dense_only_embeddings(monkeypatch):
    from atguigu.query_process.nodes import node_item_name_confirm, node_search_embedding, node_search_embedding_hyde
    for module in (node_item_name_confirm, node_search_embedding, node_search_embedding_hyde):
        monkeypatch.setattr(module, "get_embeddings", lambda texts: {"dense": [[1, 0] for _ in texts]})
        def search(collection_name, dense_data, limit=10, output_fields=None, expr=None):
            return [[{"entity": {"item_name": "device", "content": "match"}, "distance": 0.9}]]
        monkeypatch.setattr(module, "search_dense", search)
    assert node_item_name_confirm.NodeItemNameConfirm().get_final_search_item_names(["device"])[0]["search_item_name"] == "device"
    assert node_search_embedding.NodeSearchEmbedding().process({"rewritten_query": "question", "item_names": ["device"]})["embedding_chunks"][0]["content"] == "match"
    assert node_search_embedding_hyde.NodeSearchEmbeddingHyde().get_hyde_embedding_chunks(["device"], "hypothesis")[0]["content"] == "match"
