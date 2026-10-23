"""Original upload contract with portable paths and explicit terminal failures."""
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from atguigu.config.config import PROJECT_ROOT, RuntimeConfig, MinIoConfig
from atguigu.tool.logger import logger
from atguigu.business.security import legacy_data_closed
from atguigu.tool.task_utils import (add_running_task, add_done_task, get_task_info,
    update_task_status, set_task_error, TASK_STATUS_PROCESSING, TASK_STATUS_COMPLETED, TASK_STATUS_FAILED)

app = FastAPI(title="掌柜智库导入基线", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=RuntimeConfig.cors_origins,
                   allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])

@app.get("/", include_in_schema=False)
def page():
    return FileResponse(PROJECT_ROOT / "atguigu/web/page/import.html")

@app.get("/health")
def health():
    return {"status": "ok", "service": "import", "dependencies": "not_checked", "task_storage": "memory"}

def run_main_graph(task_id: str, local_dir: str, local_file_path: str):
    try:
        from atguigu.tool.minio_client_tool import get_minio_client
        from atguigu.import_process.main_graph import MainGraphRunner
        add_running_task(task_id, "backup_file")
        get_minio_client().fput_object(
            bucket_name=MinIoConfig.minio_bucket_name,
            object_name=f"source/{task_id}/{Path(local_file_path).name}", file_path=local_file_path)
        add_done_task(task_id, "backup_file")
        MainGraphRunner.create_and_run({"task_id": task_id, "local_dir": local_dir, "local_file_path": local_file_path})
        update_task_status(task_id, TASK_STATUS_COMPLETED)
    except Exception as exc:
        # No exception text: SDK messages can contain signed URLs or credentials.
        logger.error("导入任务失败 task_id=%s type=%s", task_id, type(exc).__name__)
        set_task_error(task_id, f"导入失败（{type(exc).__name__}），请检查模型与存储配置，并运行 scripts/doctor.py")
        update_task_status(task_id, TASK_STATUS_FAILED)

@app.post("/upload", dependencies=[Depends(legacy_data_closed)])
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    filename = file.filename or ""
    if not filename or filename in {".", ".."} or any(c in filename for c in '/\\:\x00'):
        await file.close()
        raise HTTPException(400, "文件名不合法")
    if Path(filename).suffix.lower() not in {".pdf", ".md"}:
        await file.close()
        raise HTTPException(415, "阶段一原解析器仅支持 PDF 和 Markdown")
    task_id = str(uuid.uuid4())
    local_dir = RuntimeConfig.data_dir / datetime.now(timezone.utc).strftime("%Y%m%d") / task_id
    local_dir.mkdir(parents=True, exist_ok=False)
    target = local_dir / filename
    size = 0
    try:
        with target.open("xb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > RuntimeConfig.upload_max_bytes:
                    raise HTTPException(413, "文件超过 UPLOAD_MAX_MB 限制")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "文件不能为空")
    except Exception:
        target.unlink(missing_ok=True)
        local_dir.rmdir()
        raise
    finally:
        await file.close()
    update_task_status(task_id, TASK_STATUS_PROCESSING)
    add_done_task(task_id, "upload_file")
    background_tasks.add_task(run_main_graph, task_id, str(local_dir), str(target))
    return {"task_id": task_id, "file_size": size, "file_name": filename}

@app.get("/status/{task_id}", dependencies=[Depends(legacy_data_closed)])
def get_status(task_id: str):
    result = get_task_info(task_id)
    if not result["status"]:
        raise HTTPException(404, "任务不存在或进程已经重启")
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=RuntimeConfig.host, port=RuntimeConfig.import_port)
