"""Original local UI reference. Legacy data routes are closed since stage 2."""
import asyncio
import json
import uuid
from queue import Empty

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, Depends
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pymongo.errors import PyMongoError

from atguigu.config.config import PROJECT_ROOT, RuntimeConfig
from atguigu.tool.logger import logger
from atguigu.business.security import legacy_data_closed
from atguigu.tool.mongo_client_tool import get_recent_history_list, clear_history
from atguigu.tool.task_utils import (update_task_status, set_task_error, get_task_info,
    TASK_STATUS_PROCESSING, TASK_STATUS_COMPLETED, TASK_STATUS_FAILED, create_queue, put_data, queue_dict)

app = FastAPI(title="掌柜智库检索基线", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=RuntimeConfig.cors_origins,
                   allow_credentials=False, allow_methods=["GET", "POST", "DELETE"], allow_headers=["*"])

@app.get("/", include_in_schema=False)
def page():
    return FileResponse(PROJECT_ROOT / "atguigu/web/page/chat.html")

@app.get("/health")
def health():
    return {"status": "ok", "service": "query", "dependencies": "not_checked", "task_storage": "memory"}

@app.get("/history/{session_id}", dependencies=[Depends(legacy_data_closed)])
def get_history(session_id: str):
    try:
        history = get_recent_history_list(session_id)
    except PyMongoError as exc:
        raise HTTPException(503, "MongoDB 历史服务不可用，请运行 scripts/doctor.py") from exc
    items = [{**item, "_id": str(item["_id"])} for item in history]
    items.sort(key=lambda item: item.get("ts") or 0)
    return {"items": items}

@app.delete("/history/{session_id}", dependencies=[Depends(legacy_data_closed)])
def delete_history(session_id: str):
    try:
        clear_history(session_id)
    except PyMongoError as exc:
        raise HTTPException(503, "MongoDB 历史服务不可用") from exc
    return {"msg": "删除成功"}

def run_main_graph(task_id, original_query, session_id):
    try:
        from atguigu.query_process.main_graph import MainGraphRunner
        put_data(task_id, "progress", get_task_info(task_id))
        MainGraphRunner.create_and_run({"task_id": task_id, "original_query": original_query, "session_id": session_id})
        update_task_status(task_id, TASK_STATUS_COMPLETED)
        put_data(task_id, "progress", get_task_info(task_id))
        put_data(task_id, "done", get_task_info(task_id))
    except Exception as exc:
        logger.error("查询任务失败 task_id=%s type=%s", task_id, type(exc).__name__)
        set_task_error(task_id, f"查询失败（{type(exc).__name__}），请检查模型与存储配置，并运行 scripts/doctor.py")
        update_task_status(task_id, TASK_STATUS_FAILED)
        put_data(task_id, "progress", get_task_info(task_id))
        put_data(task_id, "error", get_task_info(task_id))

class QueryParams(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    session_id: str = Field(min_length=1, max_length=128)

@app.post("/query", dependencies=[Depends(legacy_data_closed)])
def query(background_tasks: BackgroundTasks, query_params: QueryParams):
    task_id = str(uuid.uuid4())
    create_queue(task_id)
    update_task_status(task_id, TASK_STATUS_PROCESSING)
    background_tasks.add_task(run_main_graph, task_id, query_params.query, query_params.session_id)
    return {"task_id": task_id, "original_query": query_params.query, "session_id": query_params.session_id}

@app.get("/stream/{task_id}", dependencies=[Depends(legacy_data_closed)])
def stream(request: Request, task_id: str):
    queue = queue_dict.get(task_id)
    if queue is None:
        raise HTTPException(404, "流任务不存在或已结束")
    async def generate():
        try:
            while not await request.is_disconnected():
                try:
                    item = queue.get_nowait()
                except Empty:
                    await asyncio.sleep(0.1)
                    continue
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
                if item["event"] in {"error", "done"}:
                    break
        finally:
            queue_dict.pop(task_id, None)
    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=RuntimeConfig.host, port=RuntimeConfig.query_port)
