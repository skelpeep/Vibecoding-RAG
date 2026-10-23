"""Durable submissions and presentation shared by HTTP routes and version editing."""
import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from atguigu.business.import_errors import ImportFailure
from atguigu.business.import_parser import safe_relative_path
from atguigu.business.knowledge_storage import get_storage
from atguigu.business.models import ImportBatch, ImportTask, KnowledgeUnit, KnowledgeVersion, OutboxEvent, StoredFile, User, new_id
from atguigu.config.config import ImportConfig, RuntimeConfig


@dataclass
class UploadInput:
    name: str
    data: bytes
    content_type: str = "application/octet-stream"
    relative_path: str | None = None


def timestamp(value):
    return value.isoformat() + "Z" if value else None


def task_payload(task, *, file=None, detailed=True):
    result = {"id": task.id, "batch_id": task.batch_id, "status": task.status, "stage": task.stage,
              "attempts": task.attempts, "max_attempts": task.max_attempts,
              "created_at": timestamp(task.created_at), "updated_at": timestamp(task.updated_at)}
    if detailed:
        progress = task.progress_json or {}
        result.update(unit_id=task.unit_id, version_id=task.version_id,
                      file_name=file.file_name if file else progress.get("file_name"),
                      file_size=file.file_size if file else progress.get("file_size", 0),
                      relative_path=progress.get("relative_path"), error_code=task.error_code,
                      error_message=task.error_message, retry_at=timestamp(task.retry_at),
                      progress={k: v for k, v in progress.items() if k in {"percent", "chunk_count", "warnings", "image_count"}},
                      can_retry=(task.status == "failed" or task.status == "pending" and task.stage == "retry_wait")
                                and task.attempts < task.max_attempts and bool(progress.get("retryable")))
    return result


def refresh_batch(db, batch_id):
    batch = db.get(ImportBatch, batch_id)
    db.flush()
    statuses = list(db.scalars(select(ImportTask.status).where(ImportTask.batch_id == batch_id)))
    if "processing" in statuses:
        batch.status = "processing"
    elif "pending" in statuses:
        batch.status = "pending"
    elif statuses and all(s == "completed" for s in statuses):
        batch.status = "completed"
    elif "completed" in statuses:
        batch.status = "partial_failed"
    elif statuses and all(s == "cancelled" for s in statuses):
        batch.status = "cancelled"
    else:
        batch.status = "failed"
    return batch


def batch_payload(db, batch, *, detailed=True, include_tasks=True, can_view_task=None):
    tasks = db.scalars(select(ImportTask).where(ImportTask.batch_id == batch.id).order_by(ImportTask.created_at, ImportTask.id)).all()
    counts = {status: sum(t.status == status for t in tasks) for status in ["pending", "processing", "completed", "failed", "cancelled"]}
    # Derive aggregate state when simultaneous workers complete; no stale summary is exposed.
    status = ("processing" if counts["processing"] else "pending" if counts["pending"] else
              "completed" if counts["completed"] == len(tasks) and tasks else
              "partial_failed" if counts["completed"] else "cancelled" if counts["cancelled"] == len(tasks) and tasks else "failed")
    result = {"id": batch.id, "batch_id": batch.id, "status": status, "file_count": batch.file_count,
              "counts": counts, "created_at": timestamp(batch.created_at), "updated_at": timestamp(batch.updated_at)}
    if include_tasks:
        result["tasks"] = [task_payload(t, file=db.get(StoredFile, t.file_id),
            detailed=detailed and (can_view_task(t) if can_view_task else True)) for t in tasks]
    return result


def _store_source(db, owner_id, unit, version, upload, batch, key, *, operation):
    source_id = new_id()
    extension = PurePosixPath(upload.name.replace("\\", "/")).suffix.lower()
    object_key = f"units/{unit.id}/versions/{version.id}/source/{source_id}{extension if len(extension) < 16 else ''}"
    storage = get_storage()
    storage.put_bytes(object_key, upload.data, upload.content_type)
    source = StoredFile(id=source_id, owner_id=owner_id, unit_id=unit.id, version_id=version.id,
        file_name=upload.name.replace("\\", "/").rsplit("/", 1)[-1][:255] or "unnamed", object_key=object_key,
        bucket=storage.bucket, purpose="source", content_type=upload.content_type[:100],
        file_size=len(upload.data), sha256=hashlib.sha256(upload.data).hexdigest())
    db.add(source)
    db.flush()
    task = ImportTask(id=new_id(), batch_id=batch.id, owner_id=owner_id, unit_id=unit.id, version_id=version.id,
        file_id=source.id, idempotency_key=key, max_attempts=ImportConfig.max_attempts,
        progress_json={"percent": 0, "file_name": source.file_name, "file_size": source.file_size,
            "relative_path": upload.relative_path or upload.name, "operation": operation,
            "permission_revision": unit.permission_revision, "retryable": False})
    db.add(task)
    db.flush()
    return task


def _validate_upload(upload):
    safe_relative_path(upload.relative_path or upload.name)
    safe_relative_path(upload.name)
    if len(upload.data) > RuntimeConfig.upload_max_bytes:
        raise ImportFailure("FILE_SIZE_LIMIT", "文件超过单文件大小限制")
    extension = PurePosixPath(upload.name).suffix.lower()
    if extension == ".doc":
        raise ImportFailure("LEGACY_DOC_UNSUPPORTED", "旧版 .doc 暂不支持，请另存为 .docx 后上传")
    if extension not in {".txt", ".md", ".markdown", ".pdf", ".docx"}:
        raise ImportFailure("UNSUPPORTED_FORMAT", "支持 PDF、DOCX、Markdown 和 TXT 格式")
    if not upload.data:
        raise ImportFailure("EMPTY_FILE", "文件为空")


def enqueue_uploads(db, owner_id, uploads, idempotency_key, *, category=""):
    if not 1 <= len(uploads) <= ImportConfig.max_files:
        raise HTTPException(422, f"每批需要 1 至 {ImportConfig.max_files} 个文件")
    if sum(len(u.data) for u in uploads) > ImportConfig.batch_max_bytes:
        raise HTTPException(413, "批次文件总大小超过限制")
    # Serialize same-owner submissions so concurrent retries cannot create duplicate units.
    db.scalar(select(User).where(User.id == owner_id).with_for_update())
    existing = db.scalar(select(ImportBatch).where(ImportBatch.owner_id == owner_id, ImportBatch.idempotency_key == idempotency_key))
    if existing:
        tasks = db.scalars(select(ImportTask).where(ImportTask.batch_id == existing.id).order_by(ImportTask.idempotency_key)).all()
        signatures = [(db.get(StoredFile, t.file_id).sha256, (t.progress_json or {}).get("relative_path")) for t in tasks]
        if signatures != [(hashlib.sha256(u.data).hexdigest(), u.relative_path or u.name) for u in uploads]:
            raise HTTPException(409, "此幂等键已用于另一批文件，请使用新的幂等键")
        return existing
    batch = ImportBatch(id=new_id(), owner_id=owner_id, idempotency_key=idempotency_key, file_count=len(uploads))
    db.add(batch)
    db.flush()
    for index, upload in enumerate(uploads):
        name = upload.name.replace("\\", "/").rsplit("/", 1)[-1][:255] or "unnamed"
        unit = KnowledgeUnit(id=new_id(), unit_code="KU-" + uuid4().hex, title=PurePosixPath(name).stem[:255] or name,
            category=category, creator_id=owner_id, source_file_name=name, file_type=PurePosixPath(name).suffix.lstrip(".")[:20],
            file_size=len(upload.data), status="draft")
        db.add(unit)
        db.flush()
        version = KnowledgeVersion(id=new_id(), unit_id=unit.id, version_number=1, creator_id=owner_id, status="pending",
            metadata_json={"title": unit.title, "summary": "", "category": category, "tags": [],
                           "source_file_name": name, "file_type": unit.file_type, "file_size": unit.file_size})
        db.add(version)
        db.flush()
        db.add(OutboxEvent(event_type="unit.created", aggregate_id=unit.id,
            payload_json={"unit_id": unit.id, "version_id": version.id, "status": "draft",
                          "invalidate": ["knowledge", "retrieval", "faq"]}))
        task = _store_source(db, owner_id, unit, version, upload, batch, f"{index:06d}", operation="knowledge:import")
        try:
            _validate_upload(upload)
        except ImportFailure as error:
            task.status, task.stage, task.error_code, task.error_message = "failed", "failed", error.code, error.message
            version.status = "failed"
    db.flush()
    refresh_batch(db, batch.id)
    return batch


def enqueue_version(db, owner_id, unit, version, upload=None, idempotency_key=None):
    if version.status != "pending" or version.unit_id != unit.id or version.creator_id != owner_id:
        raise HTTPException(409, "版本不可入队")
    existing = db.scalar(select(ImportTask).where(ImportTask.version_id == version.id))
    if existing:
        return existing
    if upload is None:
        content = version.content
        inherited = {}
        pattern = r"/api/knowledge/files/([0-9a-f-]{36})/(?:image|content)"
        for file_id in set(re.findall(pattern, content)):
            original = db.get(StoredFile, file_id)
            if not original or original.unit_id != unit.id or original.purpose not in {"image", "attachment"} or original.content_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                raise HTTPException(422, "正文包含不属于此知识的图片引用")
            if original.version_id == version.id:
                inherited[file_id] = file_id
                continue
            new_file_id = new_id()
            key = f"units/{unit.id}/versions/{version.id}/images/inherited/{new_file_id}"
            storage = get_storage()
            data = storage.get_bytes(original.object_key, bucket=original.bucket)
            storage.put_bytes(key, data, original.content_type)
            db.add(StoredFile(id=new_file_id, owner_id=owner_id, unit_id=unit.id, version_id=version.id,
                file_name=original.file_name, object_key=key, bucket=storage.bucket, purpose="image",
                content_type=original.content_type, file_size=len(data), sha256=hashlib.sha256(data).hexdigest()))
            inherited[file_id] = new_file_id
        content = re.sub(pattern, lambda m: f"/api/knowledge/files/{inherited[m.group(1)]}/image", content)
        version.content = content
        upload = UploadInput("edited.md", content.encode("utf-8"), "text/markdown")
    _validate_upload(upload)
    batch = ImportBatch(id=new_id(), owner_id=owner_id, idempotency_key=idempotency_key or "version:" + version.id, file_count=1)
    db.add(batch)
    db.flush()
    operation = "knowledge:create" if version.version_number == 1 and not unit.active_version_id else "knowledge:update"
    return _store_source(db, owner_id, unit, version, upload, batch, "version:" + version.id, operation=operation)


def retry_task(db, task):
    task = db.scalar(select(ImportTask).where(ImportTask.id == task.id).with_for_update().execution_options(populate_existing=True))
    if task.status == "pending":
        if task.stage == "retry_wait":
            task.retry_at = None
        return task
    if task.status != "failed" or task.attempts >= task.max_attempts or not (task.progress_json or {}).get("retryable"):
        raise HTTPException(409, "任务不可重试或已达到尝试上限")
    unit = db.get(KnowledgeUnit, task.unit_id)
    if not unit or unit.status in {"deleted", "disabled"}:
        raise HTTPException(409, "知识已删除或停用")
    task.status, task.stage, task.retry_at = "pending", "uploaded", None
    task.worker_id, task.lease_until = None, None
    task.error_code = task.error_message = None
    db.get(KnowledgeVersion, task.version_id).status = "pending"
    refresh_batch(db, task.batch_id)
    return task
