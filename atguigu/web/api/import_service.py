import shutil
import uuid
from pathlib import Path

import fastapi
import uvicorn
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from starlette.middleware.cors import CORSMiddleware
from datetime import datetime

from atguigu.config.config import MinIoConfig
from atguigu.import_process.main_graph import MainGraphRunner
from atguigu.tool.logger import logger
from atguigu.tool.minio_client_tool import get_minio_client
from atguigu.tool.task_utils import add_running_task, add_done_task, get_task_info, update_task_status, \
    TASK_STATUS_PROCESSING, TASK_STATUS_COMPLETED, TASK_STATUS_FAILED

app = FastAPI(
    title="掌柜智库导入模块对应的接口服务",
    description="导入模块各个api接口服务",
    version="0.0.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 执行graph的后台任务函数
def run_main_graph(task_id:str,local_dir:str,local_file_path:str):
    try:
        init_state = {
            "task_id": task_id,
            "local_dir": local_dir,
            "local_file_path": local_file_path
        }
        update_task_status(task_id,TASK_STATUS_PROCESSING)
        MainGraphRunner.create_and_run(init_state)
        update_task_status(task_id, TASK_STATUS_COMPLETED)
    except Exception as e:
        logger.error(f"执行graph异常，task_id={task_id}")
        update_task_status(task_id, TASK_STATUS_FAILED)


@app.post("/upload")
async def upload_file(background_tasks:BackgroundTasks, file: UploadFile = File(...,description="上传的文件对象")):
    #第一步生成task_id  uuid
    task_id = str(uuid.uuid4())


    # 上传文件的状态追踪
    add_running_task(task_id,"upload_file") #本质就是把upload_file放入正在执行的列表的中



    #接收文件并且保准到指定位置
    local_dir = rf"D:\output\{datetime.now().strftime('%Y%m%d')}"
    local_dir_obj = Path(local_dir)
    if not local_dir_obj.exists():
        local_dir_obj.mkdir(parents=True,exist_ok=True)
    local_file_path = str(local_dir_obj / file.filename)

    with open(local_file_path, "wb") as f:
        shutil.copyfileobj(file.file, f, 1024*1024)
    logger.info(f"文件上传成功，保存路径为：{local_file_path}")



    #备份文件到minio
    minio_client = get_minio_client()
    minio_client.fput_object(
        bucket_name=MinIoConfig.minio_bucket_name,
        object_name=f"pdf_file/{datetime.now().strftime('%Y%m%d')}/{task_id}/{file.filename}",
        file_path=local_file_path
    )
    logger.info(f"文件上传到minio成功，保存路径为：pdf_file/{datetime.now().strftime('%Y%m%d')}/{task_id}/{file.filename}")

    # 更新上传文件的状态追踪
    add_done_task(task_id,"upload_file")#本质就是把upload_file从正在执行的列表中移除，添加到已完成列表中





    # 调用后台任务，链接graph，执行整个graph任务
    background_tasks.add_task(run_main_graph,task_id=task_id,local_dir=local_dir,local_file_path=local_file_path)


    #返回响应 最主要的就是task_id
    # 这里我们返数据其实主要的极速task_id，其余的数据我们要和前端页面对，前端页面需要但是没有，我们就要返，如果前端需要但是已经存在了
    # 说明前端人员已经把这个活干了，我们就不需要再返了
    return {"task_id": task_id,"file_size":file.size,"file_name":file.filename}





@app.get("/status/{task_id}")
async def get_status(task_id: str = fastapi.Path(...,description="任务ID")):
    return get_task_info(task_id)





if __name__ == '__main__':
    uvicorn.run(app, host="0.0.0.0", port=8000)

