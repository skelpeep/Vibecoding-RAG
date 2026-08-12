# atguigu/query_process/nodes/node_item_name_confirm.py

import json
from langchain.chat_models import init_chat_model
from atguigu.config.config import LLMConfig, MilvusConfig
from atguigu.config.prompt import ITEM_NAME_EXTRACT_SYSTEM_PROMPT, ITEM_NAME_EXTRACT_TEMPLATE
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.bgem3_client_tool import get_bge_m3_embedding
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import create_reqs, search_hybird
from atguigu.tool.mongo_client_tool import add_or_update_history, get_recent_history_list, update_item_names_and_query


class NodeItemNameConfirm(NodeBase):
    """
    节点功能：确认用户问题中的核心商品名称。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_item_name_confirm"


    def handler_history(self, answer, final_item_names, message_id, rewritten_query, session_id):
        #       判断answer有没有值来处理历史记录
        #         如果answer有值，代表一定有新的历史记录（添加历史记录）
        #         如果没有，代表不需要添加新的历史记录
        #         不管有没有answer，我们都要给历史记录回填item_names和rewritten_query
        if answer:
            message_id = add_or_update_history(session_id, "assistant", answer)
        #       回填数据，给历史记录最近的n条去做回填，还得再去找一下最近的n条历史记录。
        #       如果有answer，我们其实回填的item_names是空列表，如果没answer那就是把final_item_names给了item_names
        history_list = get_recent_history_list(session_id, limit=10)
        ids = [history.get("_id") for history in history_list]
        if ids:
            update_item_names_and_query(ids, final_item_names, rewritten_query)
        return message_id

    def align_item_names(self, answer, final_item_names, final_search_item_names):
        #           对齐名字，通过分数来确定最终确认的名字或者候选的名字
        confirm_item_names = [
            item.get("search_item_name")
            for item in final_search_item_names
            if item.get("score") >= 0.85
        ]
        option_item_names = [
            item.get("search_item_name")
            for item in final_search_item_names
            if item.get("score") >= 0.6 and item.get("score") < 0.85
        ]
        if confirm_item_names:
            final_item_names = confirm_item_names
            answer = ""
        elif option_item_names:
            final_item_names = []
            answer = f"请确认你要咨询的商品是这些的哪一个？{",".join(option_item_names)}"
        else:
            final_item_names = []
            answer = f"对不起，我无法识别你要咨询的商品名称,请重新提问。"
        return answer, final_item_names

    def get_final_search_item_names(self, item_names):
        # 对整个item_names向量化，遍历每个item_name进行混合搜索,整理结果
        # 我们拿到了item_names和rewritten_query，接下来需要把item_names进行向量化，从milvus的item_name表当中进行混合检索
        # 看看能不能找到相似度高的item_name,如果找到了，最终的item_name才有可能确定下来
        # 准备去milvus进行混合检索，所以先去把混合检索的工具函数定义好
        embeddings = get_bge_m3_embedding(item_names)
        collection_name = MilvusConfig.item_name_collection
        final_search_item_names = []
        for idx, item_name in enumerate(item_names):
            dense_data = embeddings.get("dense")[idx]
            sparse_data = embeddings.get("sparse")[idx]

            #               准备混合检索
            reqs = create_reqs(
                dense_data=dense_data,
                sparse_data=sparse_data,
                dense_anns_field="dense_vector",
                sparse_anns_field="sparse_vector",
            )

            res = search_hybird(
                collection_name=collection_name,
                reqs=reqs,
                ranker=(0.8, 0.2),
                limit=10,
                output_fields=["item_name"]
            )
            print(json_format(res))
            print(res[0])

            search_item_names = [
                {
                    "original_item_name": item_name,
                    "search_item_name": item.get("entity", {}).get("item_name", ""),
                    "score": item.get("distance")
                }
                for item in res[0]
            ]
            final_search_item_names.extend(search_item_names)
        return final_search_item_names

    def get_item_names(self, history_content, original_query):
        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider="openai",
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_api_base,
            temperature=LLMConfig.llm_default_temperature,
        )
        messages = [
            {"role": "system", "content": ITEM_NAME_EXTRACT_SYSTEM_PROMPT},
            {"role": "user",
             "content": ITEM_NAME_EXTRACT_TEMPLATE.format(history_text=history_content, original_query=original_query)},
        ]
        res = llm.invoke(input=messages)
        # print(res.content)
        #         对大模型输出的返回信息进行整理和判断
        res_json = res.content
        #       1、大模型在返回json的时候有概率给你输出一个json的md代码块，此时我们要把```json和```去掉
        if res_json.startswith("```json"):
            res_json = res_json.replace("```json", "").replace("```", "")
        # 2 把json转化为字典（反序列化），取出item_names，判断如果有值，那么把所有的item_name去除一下空白
        res_dict = json.loads(res_json)
        item_names = res_dict.get("item_names")
        rewritten_query = res_dict.get("rewritten_query")
        if item_names:
            item_names = [
                item_name.replace(" ", "").replace("\n", "").replace("\t", "")
                for item_name in item_names
            ]
        else:
            item_names = []
        if not rewritten_query:
            rewritten_query = original_query
        return item_names, rewritten_query

    def get_history_content(self, state):
        session_id = state.get("session_id")
        if not session_id:
            logger.error("session_id必须传递")
            raise ValueError("session_id必须传递")
        original_query = state.get("original_query")
        if not original_query:
            logger.error("original_query必须传递")
            raise ValueError("original_query必须传递")
        #         拿到session_id和original_query就代表这一次提问就可以添加到历史记录当中了
        message_id = add_or_update_history(session_id, "user", original_query)
        # print(message_id)
        #         从历史记录当中获取最近的10条，然后把内容拼接成一个大串，然后让大模型根据这个大串，帮我们识别主体名字及修改原始问题
        history_list = get_recent_history_list(session_id, limit=10)
        history_content = ""
        for history in history_list:
            role = history.get("role")
            text = history.get("text")
            content = f"{role}: {text}\n"
            history_content += content
        return history_content, message_id, original_query, session_id


    def process(self, state: QueryGraphState):
        # 第一大步：获取state当中的session_id和original_query，然后根据sessionid获取最近的10条记录整理成大串
        history_content, message_id, original_query, session_id = self.get_history_content(state)
        #       整理完数据，准备调用llm
#         print(history_content)
#        第二大步：根据大串调用大模型进行意图识别，获取到意图识别出来的item_names和rewritten_query
        item_names, rewritten_query = self.get_item_names(history_content, original_query)

        answer = ""
        final_item_names = []
        if item_names:
            # 第三大步：对item_names进行向量化，然后去milvus中进行混合检索，整理成字典列表final_search_item_names
            final_search_item_names = self.get_final_search_item_names(item_names)

            # 第四大步：根据final_search_item_names的分数来确定最终的确认名字或者候选的名字，对齐名字及设置最终的answer和最终的item_names
            answer, final_item_names = self.align_item_names(answer, final_item_names, final_search_item_names)

        # 第五大步：根据最终的answer来处理更新历史记录
        message_id = self.handler_history(answer, final_item_names, message_id, rewritten_query, session_id)

        return {
            "message_id":message_id,
            "original_query":original_query,
            "answer":answer,
            "item_names":final_item_names,
            "rewritten_query": rewritten_query,
            "history":get_recent_history_list(session_id,limit=10)
        }

if __name__ == "__main__":
    # 模拟会话历史
    session_id = "test_001"
    # add_or_update_history(session_id, "user", "咨询下烫金机。")
    # add_or_update_history(session_id, "assistant", "您好。请问是哪个型号")
    # add_or_update_history(session_id, "user", "hak180")
    # add_or_update_history(session_id, "assistant", "具体有什么问题呢？")

    # 初始化图状态
    init_state = {
        "session_id": "test_001",
        "original_query": "咋用？"
    }

    # 创建节点对象
    node_item_name_confirm = NodeItemNameConfirm()
    # 执行节点的单元测试
    result = node_item_name_confirm(init_state)
    # 将返回的图状态进行json序列化
    logger.info(json_format(result))