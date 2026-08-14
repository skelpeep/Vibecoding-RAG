# atguigu/query_process/nodes/node_search_embedding.py
import json

from atguigu.config.config import MilvusConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.bgem3_client_tool import get_bge_m3_embedding
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import create_reqs, search_hybird


class NodeSearchEmbedding(NodeBase):
     """
    节点功能：基于已确认主体名+改写后的用户问题，执行Milvus向量数据库混合检索
    """

     # 覆盖基类的 name 属性，标识节点名称
     name: str = "node_search_embedding"

     def process(self, state: QueryGraphState):
         rewritten_query = state.get("rewritten_query")
         item_names = state.get("item_names")
         if not rewritten_query:
             logger.error("rewritten_query必须存在")
             raise ValueError("rewritten_query必须存在")

         if not item_names:
             logger.error("item_names必须有值")
             raise ValueError("item_names必须有值")

         embeddings = get_bge_m3_embedding([rewritten_query])
         collection_name = MilvusConfig.chunks_collection
         dense_data = embeddings.get("dense")[0]
         sparse_data = embeddings.get("sparse")[0]

         # 整理item_name json.dumps(item_names) 里面已经帮我们把一些特殊字符处理过了，所以手动就可以免了
         # item_names = [
         #     item.replace("\\",'\\\\').replace("'","\\'").replace('"', '\\"')
         #     for item in item_names
         # ]
         # 混合搜索添加标量字段过滤
         expr = f"item_name in {json.dumps(item_names,ensure_ascii=False)}" #要求in 后面的列表也是一个字符串，json序列化是最简单的


         reqs = create_reqs(
             dense_data=dense_data,
             sparse_data=sparse_data,
             dense_anns_field="dense_vector",
             sparse_anns_field="sparse_vector",
             expr=expr  #过滤自己的数据，不要其它不存在item_names里面的数据
         )

         res = search_hybird(
             collection_name=collection_name,
             reqs=reqs,
             ranker=(0.8,0.2),
             output_fields=["id","title","file_title","content","item_name"],
             limit=10,
         )
         # logger.info(json_format(res[0])

         embedding_chunks = [
             {
                 **item.get("entity",{}),
                 "score":item.get("distance"),
                 "source":"local"
             }

             for item in res[0]
         ]

         # logger.info(json_format(embedding_chunks))

         return {
            "embedding_chunks": embedding_chunks
         }







if __name__ == "__main__":
    init_state = {
        "rewritten_query": "关于BrotherHAK180烫金机如何使用",
        "item_names": ["BrotherHAK180烫金机"]
    }
    node_search_embedding = NodeSearchEmbedding()
    result = node_search_embedding(init_state)
    logger.info(json_format(result))