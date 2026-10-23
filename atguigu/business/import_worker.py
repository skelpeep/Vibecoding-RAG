"""Independent bounded worker with MySQL leases, heartbeats and fenced commits.

Run ``python -m atguigu.cli worker``; no request background tasks or caller paths.
Each slot is a subprocess, allowing a stalled parser/model process to be terminated.
"""
import base64
import hashlib
import logging
import multiprocessing
import os
import re
import signal
import threading
import time
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from atguigu.business.database import get_engine
from atguigu.business.import_errors import ImportFailure, LeaseLost, classify_error
from atguigu.business.import_parser import parse_document, split_document
from atguigu.business.import_service import refresh_batch
from atguigu.business.knowledge_index import get_index
from atguigu.business.knowledge_storage import get_storage
from atguigu.business.models import ImportTask, KnowledgeChunk, KnowledgeUnit, KnowledgeVersion, OutboxEvent, StoredFile, User, utcnow
from atguigu.business.security import load_principal
from atguigu.config.config import ImportConfig, LLMConfig, RuntimeConfig
from atguigu.tool.embedding_client_tool import get_embeddings

logger = logging.getLogger("knowledge.worker")


def _session(engine=None):
    return Session(engine or get_engine(), expire_on_commit=False)


def _eligible(task, db):
    unit, version, source, user = (db.get(KnowledgeUnit, task.unit_id), db.get(KnowledgeVersion, task.version_id),
                                   db.get(StoredFile, task.file_id), db.get(User, task.owner_id))
    if not unit or not version or not source or not user:
        raise ImportFailure("INVALID_OWNERSHIP", "任务关联记录不存在")
    if version.unit_id != unit.id or version.creator_id != task.owner_id or source.owner_id != task.owner_id or source.unit_id != unit.id or source.version_id != version.id:
        raise ImportFailure("INVALID_OWNERSHIP", "任务关联归属校验失败")
    if user.status != "active":
        raise ImportFailure("OWNER_DISABLED", "任务提交账号已停用")
    principal = load_principal(db, user)
    operation = (task.progress_json or {}).get("operation", "knowledge:import")
    if operation not in principal.permissions:
        raise ImportFailure("PERMISSION_REVOKED", "任务提交账号的操作权限已撤销")
    if unit.status in {"disabled", "deleted"}:
        raise ImportFailure("UNIT_UNAVAILABLE", "知识已停用或删除，任务已取消")
    if unit.creator_id != user.id:
        from atguigu.business.authorization import authorized_units
        if unit.id not in authorized_units(db, principal, [unit.id], published=False):
            raise ImportFailure("PERMISSION_REVOKED", "知识授权已撤销")
    if version.status == "retired" or unit.active_version_id == version.id:
        raise ImportFailure("VERSION_UNAVAILABLE", "当前版本不可重新构建")
    return unit, version, source


def _locked_task(db, task_id, token):
    task = db.scalar(select(ImportTask).where(ImportTask.id == task_id).with_for_update().execution_options(populate_existing=True))
    if not task or task.status != "processing" or task.worker_id != token or not task.lease_until or task.lease_until <= utcnow():
        raise LeaseLost()
    return task


def _claim_candidate(engine=None):
    """Only short DB transactions. Every claim has an unpredictable fencing token."""
    with _session(engine) as db, db.begin():
        now = utcnow()
        query = select(ImportTask).where(or_(
            and_(ImportTask.status == "pending", or_(ImportTask.retry_at.is_(None), ImportTask.retry_at <= now)),
            and_(ImportTask.status == "processing", ImportTask.lease_until <= now)))
        task = db.scalar(query.order_by(ImportTask.created_at, ImportTask.id).with_for_update(skip_locked=True).limit(1))
        if not task:
            return None
        if task.attempts >= task.max_attempts:
            task.status, task.stage, task.error_code, task.error_message = "failed", "failed", "LEASE_EXHAUSTED", "执行租约过期且已达到尝试上限"
            task.worker_id = task.lease_until = None
            if task.version_id:
                db.get(KnowledgeVersion, task.version_id).status = "failed"
            refresh_batch(db, task.batch_id)
            return False
        try:
            _, version, _ = _eligible(task, db)
        except ImportFailure as error:
            task.status, task.stage, task.error_code, task.error_message = "cancelled", "cancelled", error.code, error.message
            task.worker_id = task.lease_until = None
            refresh_batch(db, task.batch_id)
            return False
        token = str(uuid4())
        task.status, task.stage, task.worker_id = "processing", "parsing", token
        task.attempts += 1
        task.retry_at = task.error_code = task.error_message = None
        task.lease_until = now + timedelta(seconds=ImportConfig.lease_seconds)
        task.progress_json = {**(task.progress_json or {}), "percent": 5, "started_at": now.isoformat(), "retryable": False}
        version.status = "indexing"
        refresh_batch(db, task.batch_id)
        return task.id, token


def claim_next(engine=None):
    while True:
        result = _claim_candidate(engine)
        if result is not False:
            return result


def heartbeat(task_id, token, engine=None):
    with _session(engine) as db, db.begin():
        task = _locked_task(db, task_id, token)
        _eligible(task, db)
        task.lease_until = utcnow() + timedelta(seconds=ImportConfig.lease_seconds)


def update_progress(task_id, token, stage, percent, engine=None, **extra):
    with _session(engine) as db, db.begin():
        task = _locked_task(db, task_id, token)
        _eligible(task, db)
        task.stage = stage
        task.progress_json = {**(task.progress_json or {}), "percent": percent, **extra}


def finish_failure(task_id, token, error, stage, engine=None):
    failure = classify_error(error, stage)
    with _session(engine) as db, db.begin():
        try:
            task = _locked_task(db, task_id, token)
        except LeaseLost:
            return False
        cancelled = failure.code in {"UNIT_UNAVAILABLE", "OWNER_DISABLED", "PERMISSION_REVOKED", "VERSION_UNAVAILABLE", "INVALID_OWNERSHIP"}
        task.error_code, task.error_message = failure.code, failure.message
        task.progress_json = {**(task.progress_json or {}), "retryable": failure.retryable}
        if cancelled:
            task.status = task.stage = "cancelled"
        elif failure.retryable and task.attempts < task.max_attempts:
            task.status, task.stage = "pending", "retry_wait"
            task.retry_at = utcnow() + timedelta(seconds=min(300, ImportConfig.retry_base_seconds * 2 ** (task.attempts - 1)))
        else:
            task.status = task.stage = "failed"
        task.worker_id = task.lease_until = None
        version = db.get(KnowledgeVersion, task.version_id)
        if version and version.status != "ready":
            version.status = "pending" if task.status == "pending" else "failed"
        refresh_batch(db, task.batch_id)
        return True


def _image_summary(image):
    import httpx
    if not (LLMConfig.vl_base_url and LLMConfig.vl_api_key and LLMConfig.vl_model):
        raise ImportFailure("VISION_UNCONFIGURED", "图片摘要已启用，但视觉模型配置不完整")
    response = httpx.post(f"{LLMConfig.vl_base_url}/chat/completions", timeout=RuntimeConfig.model_timeout,
        headers={"Authorization": f"Bearer {LLMConfig.vl_api_key}"}, json={"model": LLMConfig.vl_model,
        "messages": [{"role": "user", "content": [{"type": "text", "text": "请用中文简要描述图片中的知识内容，100字以内，不要使用Markdown。"},
            {"type": "image_url", "image_url": {"url": f"data:{image.content_type};base64," + base64.b64encode(image.data).decode()}}]}],
        "max_tokens": 300})
    response.raise_for_status()
    text = response.json()["choices"][0]["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ImportFailure("VISION_INVALID_RESPONSE", "视觉模型未返回有效摘要")
    return text.strip()[:600]


def _persist_images(document, task_id, token, storage, engine=None):
    records = []
    with _session(engine) as db:
        task = db.get(ImportTask, task_id)
        unit_id, version_id, owner_id = task.unit_id, task.version_id, task.owner_id
    for index, image in enumerate(document.images):
        update_progress(task_id, token, "images", 15, engine)
        # Validate content rather than trusting source XML, MIME or an extension.
        from PIL import Image
        from io import BytesIO
        try:
            with Image.open(BytesIO(image.data)) as decoded:
                if decoded.format not in {"PNG", "JPEG", "GIF", "WEBP"}:
                    raise ValueError()
                decoded.verify()
        except Exception as error:
            raise ImportFailure("INVALID_IMAGE", "文档内图片损坏或编码不受支持") from error
        file_id = str(uuid5(NAMESPACE_URL, f"kb:{version_id}:image:{index}"))
        # Objects are attempt-scoped as well: late workers cannot change a ready image.
        key = f"units/{unit_id}/versions/{version_id}/images/{token}/{file_id}"
        storage.put_bytes(key, image.data, image.content_type)
        summary = _image_summary(image) if ImportConfig.image_summaries else ""
        replacement = f"/api/knowledge/files/{file_id}/image"
        for block in document.blocks:
            block.text = block.text.replace(image.marker, replacement)
            if summary and replacement in block.text:
                block.text += "\n图片摘要：" + summary
        records.append(dict(id=file_id, owner_id=owner_id, unit_id=unit_id, version_id=version_id,
            file_name=image.name[:255], object_key=key, bucket=storage.bucket, purpose="image", content_type=image.content_type,
            file_size=len(image.data), sha256=hashlib.sha256(image.data).hexdigest()))
    return records


def complete_task(task_id, token, content, chunks, image_records, engine=None):
    with _session(engine) as db, db.begin():
        task = _locked_task(db, task_id, token)
        # Lock the unit so a concurrent disable/delete serializes with completion.
        db.scalar(select(KnowledgeUnit).where(KnowledgeUnit.id == task.unit_id).with_for_update().execution_options(populate_existing=True))
        unit, version, _ = _eligible(task, db)
        for values in image_records:
            record = db.get(StoredFile, values["id"])
            if record:
                for key, value in values.items():
                    setattr(record, key, value)
            else:
                db.add(StoredFile(**values))
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.version_id == version.id))
        db.add_all(KnowledgeChunk(**chunk, unit_id=unit.id, version_id=version.id,
                                  vector_id=f"{chunk['id']}:{token}") for chunk in chunks)
        version.content, version.content_hash, version.status = content, hashlib.sha256(content.encode()).hexdigest(), "ready"
        task.status, task.stage = "completed", "ready"
        task.worker_id = task.lease_until = task.retry_at = None
        task.progress_json = {**(task.progress_json or {}), "percent": 100, "chunk_count": len(chunks), "image_count": len(image_records)}
        db.add(OutboxEvent(event_type="unit.version.ready", aggregate_id=unit.id,
                          payload_json={"unit_id": unit.id, "version_id": version.id, "chunk_count": len(chunks),
                                        "invalidate": ["knowledge", "retrieval", "faq"]}))
        refresh_batch(db, task.batch_id)


def process_task(task_id, token, *, engine=None, storage=None, index=None, embedding=None, heartbeat_enabled=True):
    stop = threading.Event()
    lost = threading.Event()
    stage = "storage"

    def renew():
        while not stop.wait(ImportConfig.heartbeat_seconds):
            try:
                heartbeat(task_id, token, engine)
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=renew, daemon=True) if heartbeat_enabled else None
    if thread:
        thread.start()
    try:
        with _session(engine) as db, db.begin():
            task = _locked_task(db, task_id, token)
            unit, version, source = _eligible(task, db)
            source_data = {"key": source.object_key, "bucket": source.bucket, "name": source.file_name, "sha256": source.sha256}
            unit_id, version_id = unit.id, version.id
        storage = storage or get_storage()
        data = storage.get_bytes(source_data["key"], bucket=source_data["bucket"])
        if hashlib.sha256(data).hexdigest() != source_data["sha256"]:
            raise ImportFailure("SOURCE_INTEGRITY", "原文件摘要校验失败，拒绝处理已变更的对象")
        stage = "parsing"
        update_progress(task_id, token, stage, 10, engine)
        document = parse_document(data, source_data["name"])
        with _session(engine) as db:
            for block in document.blocks:
                for file_id in re.findall(r"/api/knowledge/files/([0-9a-f-]{36})/(?:image|content)", block.text):
                    linked = db.get(StoredFile, file_id)
                    if not linked or linked.unit_id != unit_id or linked.version_id != version_id or linked.purpose not in {"image", "attachment"} or linked.content_type not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
                        raise ImportFailure("INVALID_IMAGE_REFERENCE", "正文包含不可访问或不属于当前版本的图片引用")
        stage = "images"
        image_records = _persist_images(document, task_id, token, storage, engine)
        stage = "chunking"
        update_progress(task_id, token, stage, 25, engine, warnings=document.warnings)
        chunks = split_document(document, version_id)
        content = "\n\n".join(b.text for b in document.blocks)
        stage = "indexing"
        update_progress(task_id, token, stage, 30, engine, chunk_count=len(chunks))
        index = index or get_index()
        index.ensure_collection()
        embedding = embedding or get_embeddings
        for start in range(0, len(chunks), ImportConfig.embedding_batch_size):
            if lost.is_set():
                raise LeaseLost()
            batch = chunks[start:start + ImportConfig.embedding_batch_size]
            stage = "embedding"
            update_progress(task_id, token, stage, 30 + int(55 * start / len(chunks)), engine)
            vectors = embedding([c["content"] for c in batch])["dense"]
            stage = "indexing"
            update_progress(task_id, token, stage, 35 + int(55 * start / len(chunks)), engine)
            index.upsert(unit_id, version_id, token, batch, vectors)
        index.verify([f"{c['id']}:{token}" for c in chunks])
        complete_task(task_id, token, content, chunks, image_records, engine)
        return True
    except LeaseLost:
        logger.warning("task=%s lease lost; discarded result", task_id)
        return False
    except Exception as error:
        logger.warning("task=%s stage=%s error=%s", task_id, stage, type(error).__name__)
        finish_failure(task_id, token, error, stage, engine)
        return False
    finally:
        stop.set()
        if thread:
            thread.join(timeout=1)


def run_worker(*, once=False, task_id=None):
    ImportConfig.validate()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if task_id:
        raise ValueError("不接受外部指定的任务或路径；worker 只从数据库租约队列领取任务")
    context = multiprocessing.get_context("spawn")
    slots = {}
    stopping = threading.Event()

    def shutdown(*_):
        stopping.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    logger.info("worker started slots=%s", ImportConfig.concurrency)
    try:
        while not stopping.is_set():
            for process, (claimed_id, token, started) in list(slots.items()):
                if time.monotonic() - started > ImportConfig.task_timeout_seconds:
                    process.terminate()
                    process.join(5)
                    finish_failure(claimed_id, token, ImportFailure("TASK_TIMEOUT", "任务执行超过时限", True), "processing")
                    slots.pop(process)
                elif not process.is_alive():
                    process.join()
                    if process.exitcode:
                        finish_failure(claimed_id, token, ImportFailure("WORKER_EXIT", "执行进程异常退出", True), "processing")
                    slots.pop(process)
            while len(slots) < ImportConfig.concurrency and not stopping.is_set():
                claimed = claim_next()
                if not claimed:
                    break
                process = context.Process(target=process_task, args=claimed)
                process.start()
                slots[process] = (*claimed, time.monotonic())
            if once and not slots:
                break
            stopping.wait(min(ImportConfig.poll_seconds, 2))
    finally:
        for process, (claimed_id, token, _) in slots.items():
            process.terminate()
            process.join(5)
            finish_failure(claimed_id, token, ImportFailure("WORKER_SHUTDOWN", "执行器已停止，任务将重试", True), "processing")
        logger.info("worker stopped")
