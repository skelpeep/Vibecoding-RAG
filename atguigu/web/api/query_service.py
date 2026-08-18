import uuid
from queue import Queue

import uvicorn
from fastapi import FastAPI, Path, Body, BackgroundTasks
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from atguigu.query_process.main_graph import MainGraphRunner
from atguigu.tool.mongo_client_tool import get_recent_history_list, clear_history
from atguigu.tool.task_utils import update_task_status, TASK_STATUS_PROCESSING, get_task_info, TASK_STATUS_COMPLETED, \
    TASK_STATUS_FAILED

app = FastAPI(
    title="检索模块对应的接口",
    description="检索模块对应的前端接口",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# 第一步：写健康检查接口
@app.get("/health")
async def health():
    # 随便返回什么都可以，因为前端只是在判断请求是不是成功 response.ok为true ok只要状态是200即可
    return {"aa": "bb"}


#第二步：写历史记录查询接口
@app.get("/history/{session_id}")
async def get_history(session_id: str = Path(..., description="会话ID")):
    print(session_id)
#     获取历史记录，返回即可
    history_list = get_recent_history_list(session_id)
    history_list = [
        {
            "_id":str(item.get("_id")),
            "role":item.get("role",""),
            "text":item.get("text",""),
            "rewritten_query":item.get("rewritten_query",""),
            "item_names":item.get("item_names",""),
            "ts":item.get("ts",""),
            "session_id":item.get("session_id","")
        }
        for item in history_list
    ]
    return {"items":history_list} #返回数据的时候要看前端页面写的是什么，前端已经完成的情况下

#第三步：情况历史记录
@app.delete("/history/{session_id}")
async def delete_history(session_id: str = Path(..., description="会话ID")):
    clear_history(session_id)
    return {"msg":"删除成功"}


#第四步：查询接口
class QueryParams(BaseModel):
    query: str = Field(..., description="查询内容")
    session_id: str = Field(..., description="会话ID")


queue_dict = {}


def run_main_graph(task_id, original_query, session_id):
    # 造队列
    if not queue_dict.get(task_id):
        queue_dict[task_id] = Queue()

    q = queue_dict[task_id]

    try:
        init_state = {
            "task_id": task_id,
            "original_query": original_query,
            "session_id": session_id,
            "q":q
        }
        # 更新总状态，放到队列，sse后期就可以从队列当中取出更新的数据状态推送给前端
        update_task_status(task_id, TASK_STATUS_PROCESSING)
        q.put({"event":"progress","data":get_task_info(task_id)})

        MainGraphRunner.create_and_run(init_state)
        # 更新总状态，放到队列，sse后期就可以从队列当中取出更新的数据状态推送给前端
        update_task_status(task_id, TASK_STATUS_COMPLETED)
        q.put({"event": "progress", "data": get_task_info(task_id)})
    except Exception as e:
        # 更新总状态，放到队列，sse后期就可以从队列当中取出更新的数据状态推送给前端
        update_task_status(task_id, TASK_STATUS_FAILED)
        q.put({"event": "error", "data": get_task_info(task_id)})
        raise e


@app.post("/query")
async def query(background_tasks:BackgroundTasks,query_params: QueryParams = Body(...,description="查询请求体参数")):
    # 创建task_id 后期需要追踪
    task_id = str(uuid.uuid4())
    original_query = query_params.query
    session_id = query_params.session_id

    # 第五步：调后台接口任务去执行graph
    background_tasks.add_task(run_main_graph, task_id, original_query, session_id)

    return {
        "task_id": task_id,
        "original_query": original_query,
        "session_id": session_id
    }















if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8001)

