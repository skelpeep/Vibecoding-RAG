"""Authenticated multipart submissions and database-backed task polling."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from atguigu.business.authorization import authorized_units, owned_record
from atguigu.business.import_service import UploadInput, batch_payload, enqueue_uploads, retry_task, task_payload
from atguigu.business.models import AuditEvent, ImportBatch, ImportTask, KnowledgeUnit, StoredFile
from atguigu.business.security import Current, Db, Principal, require
from atguigu.config.config import ImportConfig, RuntimeConfig

router = APIRouter(prefix="/api/knowledge", tags=["持久化导入"])


def can_view_task(db, task, principal):
    if task.owner_id != principal.user.id:
        return False
    if not task.unit_id:
        return True
    unit = db.get(KnowledgeUnit, task.unit_id)
    if not unit or unit.status in {"deleted", "disabled"}:
        return False
    if unit.creator_id == principal.user.id and principal.permissions & {"knowledge:import", "knowledge:update", "knowledge:create"}:
        return True
    return task.unit_id in authorized_units(db, principal, [task.unit_id]) and task.version_id == unit.active_version_id


def require_task_read(principal):
    if not principal.permissions & {"knowledge:task:read", "knowledge:task:read-any"}:
        raise HTTPException(403, "缺少操作权限")


@router.get("/import/capabilities")
def capabilities(principal: Current):
    return {"extensions": [".pdf", ".docx", ".md", ".markdown", ".txt"],
            "max_files": ImportConfig.max_files, "max_file_bytes": RuntimeConfig.upload_max_bytes,
            "max_batch_bytes": ImportConfig.batch_max_bytes, "pdf_ocr": ImportConfig.pdf_ocr,
            "image_summaries": ImportConfig.image_summaries,
            "boundaries": ["旧 .doc 需另存为 .docx", "扫描 PDF 需要启用 OCR", "Markdown 外链和相对图片不下载", "索引完成后需显式激活版本"]}


@router.post("/import", status_code=202)
async def submit(db: Db, principal: Annotated[Principal, Depends(require("knowledge:import"))],
                 files: Annotated[list[UploadFile], File()], idempotency_key: Annotated[str, Form(min_length=1, max_length=100)],
                 relative_paths: Annotated[str | None, Form()] = None, category: Annotated[str, Form(max_length=100)] = ""):
    if not 1 <= len(files) <= ImportConfig.max_files:
        raise HTTPException(422, "批次文件数量超过限制")
    paths = None
    if relative_paths:
        try:
            paths = json.loads(relative_paths)
            if not isinstance(paths, list) or len(paths) != len(files) or any(not isinstance(p, str) for p in paths):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "relative_paths 必须是与 files 顺序一致的 JSON 字符串数组")
    uploads, total = [], 0
    try:
        for index, file in enumerate(files):
            data = await file.read(RuntimeConfig.upload_max_bytes + 1)
            if len(data) > RuntimeConfig.upload_max_bytes:
                raise HTTPException(413, "文件超过单文件大小限制")
            total += len(data)
            if total > ImportConfig.batch_max_bytes:
                raise HTTPException(413, "批次文件总大小超过限制")
            uploads.append(UploadInput(file.filename or "unnamed", data, file.content_type or "application/octet-stream",
                                       paths[index] if paths else None))
        batch = await run_in_threadpool(enqueue_uploads, db, principal.user.id, uploads, idempotency_key, category=category)
        db.add(AuditEvent(actor_id=principal.user.id, action="knowledge:import", resource_id=batch.id,
                          details_json={"file_count": batch.file_count}))
        return batch_payload(db, batch, can_view_task=lambda task: can_view_task(db, task, principal))
    finally:
        for file in files:
            await file.close()


@router.get("/batches")
def batches(db: Db, principal: Current, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    require_task_read(principal)
    query = select(ImportBatch)
    if "knowledge:task:read-any" not in principal.permissions:
        query = query.where(ImportBatch.owner_id == principal.user.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(ImportBatch.created_at.desc(), ImportBatch.id).offset((page - 1) * page_size).limit(page_size))
    return {"items": [batch_payload(db, b, include_tasks=False) for b in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/batches/{batch_id}")
def batch_info(batch_id: str, db: Db, principal: Current):
    require_task_read(principal)
    batch = owned_record(db, ImportBatch, batch_id, principal, allow_task_admin=True)
    return batch_payload(db, batch, detailed=batch.owner_id == principal.user.id,
                         can_view_task=lambda task: can_view_task(db, task, principal))


@router.get("/tasks")
def tasks(db: Db, principal: Current, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          batch_id: str | None = Query(None, max_length=36)):
    require_task_read(principal)
    query = select(ImportTask)
    if "knowledge:task:read-any" not in principal.permissions:
        query = query.where(ImportTask.owner_id == principal.user.id)
    if batch_id:
        query = query.where(ImportTask.batch_id == batch_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(ImportTask.created_at.desc(), ImportTask.id).offset((page - 1) * page_size).limit(page_size))
    return {"items": [task_payload(t, file=db.get(StoredFile, t.file_id), detailed=can_view_task(db, t, principal)) for t in rows],
            "total": total, "page": page, "page_size": page_size}


@router.get("/tasks/{task_id}")
def task_info(task_id: str, db: Db, principal: Current):
    require_task_read(principal)
    task = owned_record(db, ImportTask, task_id, principal, allow_task_admin=True)
    return task_payload(task, file=db.get(StoredFile, task.file_id), detailed=can_view_task(db, task, principal))


@router.post("/tasks/{task_id}/retry")
def retry(task_id: str, db: Db, principal: Current):
    if not principal.permissions & {"knowledge:import", "knowledge:update", "knowledge:create"}:
        raise HTTPException(403, "缺少操作权限")
    task = owned_record(db, ImportTask, task_id, principal)
    if not can_view_task(db, task, principal):
        raise HTTPException(404, "资源不存在或不可访问")
    task = retry_task(db, task)
    db.add(AuditEvent(actor_id=principal.user.id, action="knowledge:import:retry", resource_id=task.id))
    return task_payload(task, file=db.get(StoredFile, task.file_id))
