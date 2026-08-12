# atguigu/query_process/nodes/node_search_embedding_hyde.py
import json

from langchain.chat_models import init_chat_model

from atguigu.config.config import LLMConfig, MilvusConfig
from atguigu.config.prompt import HYDE_PROMPT
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.bgem3_client_tool import get_bge_m3_embedding
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import create_reqs, search_hybird


class NodeSearchEmbeddingHyde(NodeBase):
    """
    节点功能：HyDE (Hypothetical Document Embedding)
    先让 LLM 生成假设性答案，再对答案进行向量检索，提高召回率。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_search_embedding_hyde"

    def process(self, state: QueryGraphState):
        # 获取重写的问题
        item_names, rewritten_query = self.get_rewritten_query(state)
        # 生成假设性答案并合并原始问题
        merged_query = self.get_hyde_answer(rewritten_query)
        # 混合搜索获取切片
        hyde_embedding_chunks = self.get_hyde_embedding_chunks(item_names, merged_query)

        return {
            "hyde_embedding_chunks": hyde_embedding_chunks
        }

    def get_hyde_embedding_chunks(self, item_names, merged_query):
        embeddings = get_bge_m3_embedding([merged_query])
        collection_name = MilvusConfig.chunks_collection
        dense_data = embeddings.get("dense")[0]
        sparse_data = embeddings.get("sparse")[0]
        # 整理item_name
        item_names = [
            item.replace("\\", '\\\\').replace("'", "\\'").replace('"', '\\"')
            for item in item_names
        ]
        # 混合搜索添加标量字段过滤
        expr = f"item_name in {json.dumps(item_names)}"  # 要求in 后面的列表也是一个字符串，json序列化是最简单的
        reqs = create_reqs(
            dense_data=dense_data,
            sparse_data=sparse_data,
            dense_anns_field="dense_vector",
            sparse_anns_field="sparse_vector",
            expr=expr  # 过滤自己的数据，不要其它不存在item_names里面的数据
        )
        res = search_hybird(
            collection_name=collection_name,
            reqs=reqs,
            ranker=(0.8, 0.2),
            output_fields=["id", "title", "file_title", "content", "item_name"],
            limit=10,
        )
        # logger.info(json_format(res[0])
        hyde_embedding_chunks = [
            {
                **item.get("entity", {}),
                "score": item.get("distance"),
                "source": "local"
            }

            for item in res[0]
        ]
        return hyde_embedding_chunks

    def get_hyde_answer(self, rewritten_query):
        # 生成假设性答案
        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider="openai",
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_api_base,
            temperature=LLMConfig.llm_default_temperature,
        )
        messages = [
            {"role": "user", "content": HYDE_PROMPT.format(rewritten_query=rewritten_query)}
        ]
        res = llm.invoke(input=messages)
        hyde_answer = res.content
        # 合并问题与答案，生成新的检索query
        merged_query = f"{rewritten_query} {hyde_answer}"
        return merged_query

    def get_rewritten_query(self, state):
        rewritten_query = state.get("rewritten_query")
        item_names = state.get("item_names")
        if not rewritten_query:
            logger.error("rewritten_query必须存在")
            raise ValueError("rewritten_query必须存在")
        if not item_names:
            logger.error("item_names必须有值")
            raise ValueError("item_names必须有值")
        return item_names, rewritten_query


if __name__ == "__main__":
    init_state = {
        "rewritten_query": "关于BrotherHAK180烫金机如何使用",
        "item_names": ["BrotherHAK180烫金机"]
    }
    node_search_embedding_hyde = NodeSearchEmbeddingHyde()
    result = node_search_embedding_hyde(init_state)
    logger.info(json_format(result))