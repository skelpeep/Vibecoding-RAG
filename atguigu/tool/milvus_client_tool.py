from pymilvus import MilvusClient, AnnSearchRequest, WeightedRanker

from atguigu.config.config import MilvusConfig

milvus_client = None

def get_milvus_client():
    global milvus_client
    if not milvus_client:
        milvus_client = MilvusClient(
            uri=MilvusConfig.milvus_url
        )
    return milvus_client


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
        data=dense_data,
        anns_field=dense_anns_field,
        limit=limit,
        param=dense_param,
        expr=expr,
    ) #稠密
    sparse_req = AnnSearchRequest(
        data=sparse_data,
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