# atguigu/query_process/nodes/node_item_name_confirm.py

import json

from langchain.chat_models import init_chat_model
from openai import api_key

from atguigu.config.config import LLMConfig
from atguigu.config.prompt import ITEM_NAME_EXTRACT_SYSTEM_PROMPT, ITEM_NAME_EXTRACT_TEMPLATE
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger
from atguigu.tool.milvus_client_tool import milvus_client, get_milvus_client
from atguigu.tool.mongo_client_tool import add_or_update_history, get_recent_history_list


class NodeItemNameConfirm(NodeBase):
    """
    节点功能：确认用户问题中的核心商品名称。
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_item_name_confirm"

    def process(self, state: QueryGraphState):
        session_id = state.get("session_id")
        if not session_id:
            logger.error("session_id必须传递")
            raise ValueError("session_id必须传递")

        original_query = state.get("original_query")
        if not original_query:
            logger.error("original_query必须传递")
            raise ValueError("original_query必须传递")

#         拿到session_id和original_query就代表这一次提问就可以添加到历史记录当中了
        message_id = add_or_update_history(session_id,"user",original_query)
        # print(message_id)

#         从历史记录当中获取最近的10条，然后把内容拼接成一个大串，然后让大模型根据这个大串，帮我们识别主体名字及修改原始问题
        history_list = get_recent_history_list(session_id,limit=10)
        history_content = ""
        for history in history_list:
            role = history.get("role")
            text = history.get("text")
            content = f"{role}: {text}\n"
            history_content += content
#       整理完数据，准备调用llm
#         print(history_content)

        llm = init_chat_model(
            model=LLMConfig.item_model,
            model_provider="openai",
            api_key=LLMConfig.openai_api_key,
            base_url=LLMConfig.openai_api_base,
            temperature=LLMConfig.llm_default_temperature,
        )

        messages = [
            {"role": "system", "content":ITEM_NAME_EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content":ITEM_NAME_EXTRACT_TEMPLATE.format(history_text=history_content,original_query=original_query)},
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
                item_name.replace(" ","").replace("\n","").replace("\t","")
                for item_name in item_names
            ]
        else:
            item_names = []

        if not rewritten_query:
            rewritten_query = original_query



#      我们拿到了item_names和rewritten_query，接下来需要把item_names进行向量化，从milvus的item_name表当中进行混合检索
#      看看能不能找到相似度高的item_name,如果找到了，最终的item_name才有可能确定下来
#      准备去milvus进行混合检索，所以先去把混合检索的工具函数定义好


























if __name__ == '__main__':
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