from pymilvus import MilvusClient, AnnSearchRequest, WeightedRanker, RRFRanker

from atguigu.config.config import EmbeddingConfig, MilvusConfig, RuntimeConfig

milvus_client = None

def get_milvus_client():
    global milvus_client
    if not milvus_client:
        milvus_client = MilvusClient(
            uri=MilvusConfig.milvus_url,
            token=MilvusConfig.milvus_token,
            timeout=RuntimeConfig.service_timeout,
        )
    return milvus_client


def validate_dense_collection(client, collection_name, dimensions):
    """Reject incompatible existing collections without modifying stored data."""
    fields = client.describe_collection(collection_name=collection_name)["fields"]
    dense = next((field for field in fields if field["name"] == "dense_vector"), None)
    if dense is None or int(dense.get("params", {}).get("dim", 0)) != dimensions:
        raise ValueError("现有 Milvus 集合维度不匹配，请使用新集合并以当前 embedding 模型重新导入")
    if any(field["name"] == "sparse_vector" for field in fields):
        raise ValueError("现有集合使用 BGE 稀疏向量，请使用新集合并以远程 embedding 模型重新导入")


def search_dense(collection_name, dense_data, limit=10, output_fields=None, expr=None):
    client = get_milvus_client()
    validate_dense_collection(client, collection_name, EmbeddingConfig.dimensions)
    return client.search(
        collection_name=collection_name,
        data=[dense_data],
        anns_field="dense_vector",
        search_params={"metric_type": "COSINE", "params": {"nprobe": 10}},
        filter=expr or "",
        limit=limit,
        output_fields=output_fields,
        timeout=RuntimeConfig.service_timeout,
    )


# data: Union[List, utils.SparseMatrixInputType],
# anns_field: str,
# limit: int,
# param: Dict,
# expr: Optional[str] = None,


def create_reqs(
        dense_data,
        sparse_data,
        dense_anns_field=None,
        sparse_anns_field=None,
        limit=10,
        dense_param=None,
        sparse_param=None,
        expr=None
):

    if not dense_param:
        dense_param = {
            "metric_type": "COSINE",
        }
    if not sparse_param:
        sparse_param = {
            "metric_type": "IP",
        }

    dense_req = AnnSearchRequest(
        data=[dense_data],
        anns_field=dense_anns_field,
        limit=limit,
        param=dense_param,
        expr=expr,
    ) #稠密
    sparse_req = AnnSearchRequest(
        data=[sparse_data],
        anns_field=sparse_anns_field,
        limit=limit,
        param=sparse_param,
        expr=expr,
    ) #稀疏

    return [dense_req, sparse_req]


# collection_name: str,
# reqs: List[AnnSearchRequest],
# ranker: Union[BaseRanker, Function],
# limit: int = 10,
# output_fields: Optional[List[str]] = None,


def search_hybird(collection_name, reqs,ranker=(0.5,0.5),limit=10,output_fields=None):
    milvus_client = get_milvus_client()
    # 自己分配权重
    weight_ranker = WeightedRanker(ranker[0],ranker[1],norm_score=True)
    res = milvus_client.hybrid_search(
        collection_name=collection_name,
        reqs=reqs,
        ranker=weight_ranker,
        limit=limit,
        output_fields=output_fields
    )
    return res
