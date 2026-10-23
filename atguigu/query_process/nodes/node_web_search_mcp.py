# atguigu/query_process/nodes/node_web_search_mcp.py
import asyncio
import json

from atguigu.config.config import McpConfig
from atguigu.query_process.base import NodeBase
from atguigu.query_process.state import QueryGraphState
from atguigu.tool.json_format_tool import json_format
from atguigu.tool.logger import logger

class NodeWebSearchMcp(NodeBase):
    """
    节点功能，调用外部搜索引擎补充信息
    """

    # 覆盖基类的 name 属性，标识节点名称
    name: str = "node_web_search_mcp"

    def process(self, state: QueryGraphState):
        if not McpConfig.enabled:
            return {"web_search_docs": []}
        rewritten_query = state.get("rewritten_query")
        if not rewritten_query:
            logger.error("rewritten_query不能为空")
            raise ValueError("rewritten_query不能为空")

        #调用mcp
        result = asyncio.run(self.mcp_run(rewritten_query))
        search_data = json.loads(result.content[0].text).get("pages")

        return {
            "web_search_docs":[
                {
                    "title": item.get("title"),
                    "content": item.get("snippet"),
                    "url": item.get("url"),
                    "source":"web"
                }
                for item in search_data
            ]
        }



    async def mcp_run(self,query,limit=10) -> None:
        from agents.mcp import MCPServerStreamableHttp
        token = McpConfig.api_key
        async with MCPServerStreamableHttp(
            name="websearch",
            params={
                "url": McpConfig.mcp_base_url,
                "headers": {"Authorization": f"Bearer {token}"},
                "timeout": 10,
            },
            cache_tools_list=True,
            max_retry_attempts=3,
            client_session_timeout_seconds=30
        ) as server:
            result = await server.call_tool("bailian_web_search",arguments={
                "query": query,
                "count":limit
            })

            return result




if __name__ == "__main__":

    init_state = {
        "rewritten_query": "关于BrotherHAK180烫金机如何使用"
    }

    # 执行节点的业务调用
    node_web_search_mcp = NodeWebSearchMcp()
    result = node_web_search_mcp(init_state)
    logger.info(json_format(result))
