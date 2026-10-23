"""Stage-four knowledge management. Data visibility is independent of RBAC menus."""
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select

from atguigu.business import knowledge_schemas as s, knowledge_service as service, models as m
from atguigu.business.api import audit, set_grants
from atguigu.business.authorization import accessible_file, accessible_unit, visible_unit_condition
from atguigu.business.schemas import Grants
from atguigu.business.security import Current, Db, Principal, require

router = APIRouter(prefix="/api/knowledge", tags=["知识管理"])
Read = Annotated[Principal, Depends(require("knowledge:read"))]
Create = Annotated[Principal, Depends(require("knowledge:create"))]
Edit = Annotated[Principal, Depends(require("knowledge:update"))]
Delete = Annotated[Principal, Depends(require("knowledge:delete"))]
FileRead = Annotated[Principal, Depends(require("knowledge:file:read"))]


def enqueue(db, principal, unit, version):
    from atguigu.business.import_service import enqueue_version
    try:
        return enqueue_version(db, principal.user.id, unit, version)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "版本入队失败，文件存储暂不可用，请稍后重试") from None


def version_record(db, unit, version_id):
    version = db.scalar(select(m.KnowledgeVersion).where(m.KnowledgeVersion.id == version_id,
                                                       m.KnowledgeVersion.unit_id == unit.id))
    if not version:
        raise HTTPException(404, "资源不存在或不可访问")
    return version


def apply_grants(db, principal, unit, grants):
    if grants is not None:
        if "knowledge:permissions" not in principal.permissions:
            raise HTTPException(403, "缺少配置知识授权的操作权限")
        set_grants(unit.id, Grants(grants=grants), db, principal)


def snapshot_from_input(body, unit):
    return {**service.metadata(unit), "title": body.title, "summary": body.summary,
            "category": body.category.strip(), "tags": list(dict.fromkeys(body.tags))}


def inherit_attachments(db, principal, unit, source, version):
    """New versions carry their own attachment records and private object keys."""
    if not source:
        return
    files = db.scalars(select(m.StoredFile).where(m.StoredFile.unit_id == unit.id,
                      m.StoredFile.version_id == source.id, m.StoredFile.purpose == "attachment")).all()
    for original in files:
        file_id = str(uuid4())
        key = f"units/{unit.id}/versions/{version.id}/attachments/{file_id}"
        try:
            client = storage()
            data = client.get_bytes(original.object_key, bucket=original.bucket)
            client.put_bytes(key, data, content_type=original.content_type)
        except Exception:
            raise HTTPException(503, "复制版本附件失败，文件存储暂不可用，请稍后重试") from None
        db.add(m.StoredFile(id=file_id, owner_id=principal.user.id, unit_id=unit.id, version_id=version.id,
                            file_name=original.file_name, object_key=key, bucket=client.bucket,
                            purpose="attachment", content_type=original.content_type, file_size=len(data),
                            sha256=sha256(data).hexdigest()))
        version.content = version.content.replace(f"/api/knowledge/files/{original.id}/", f"/api/knowledge/files/{file_id}/")
    version.content_hash = sha256(version.content.encode()).hexdigest()
    db.flush()


@router.get("/permission-options")
def permission_options(db: Db, principal: Current, search: str = Query("", max_length=100)):
    if not principal.permissions & {"knowledge:permissions", "knowledge:preview"}:
        raise HTTPException(403, "缺少操作权限")
    users = select(m.User).where(m.User.status == "active")
    if search:
        users = users.where(m.User.display_name.contains(search, autoescape=True)
                            | m.User.username.contains(search, autoescape=True))
    return {"departments": [{"id": d.id, "name": d.name, "parent_id": d.parent_id} for d in
                            db.scalars(select(m.Department).order_by(m.Department.sort_order, m.Department.name))],
            "roles": [{"id": r.id, "role_name": r.role_name} for r in db.scalars(select(m.Role).order_by(m.Role.role_name))],
            "users": [{"id": u.id, "username": u.username, "display_name": u.display_name, "department_id": u.department_id}
                      for u in db.scalars(users.order_by(m.User.username).limit(200))]}


@router.get("/categories")
def categories(db: Db, principal: Read):
    query = select(m.KnowledgeUnit.category).where(visible_unit_condition(principal), m.KnowledgeUnit.category != "")
    return {"items": list(db.scalars(query.distinct().order_by(m.KnowledgeUnit.category)))}


@router.get("/units")
def list_units(db: Db, principal: Read, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
               search: str = Query("", max_length=200), category: str = Query("", max_length=100),
               status: Literal["draft", "published", "disabled", "deleted"] | None = None):
    query = select(m.KnowledgeUnit).where(visible_unit_condition(principal))
    if search:
        query = query.where(m.KnowledgeUnit.title.contains(search, autoescape=True)
                            | m.KnowledgeUnit.unit_code.contains(search, autoescape=True))
    if category:
        query = query.where(m.KnowledgeUnit.category == category)
    if status:
        query = query.where(m.KnowledgeUnit.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(m.KnowledgeUnit.updated_at.desc(), m.KnowledgeUnit.id)
                      .offset((page - 1) * page_size).limit(page_size))
    return {"items": [service.unit_view(db, u, principal) for u in rows], "total": total,
            "page": page, "page_size": page_size}


@router.post("/units", status_code=201)
def create_unit(body: s.UnitInput, db: Db, principal: Create):
    if not body.content.strip():
        raise HTTPException(422, "正文不能为空")
    unit = m.KnowledgeUnit(unit_code="KB-" + uuid4().hex[:20].upper(), title=body.title,
                           summary=body.summary, category=body.category.strip(), tags_json=list(dict.fromkeys(body.tags)),
                           creator_id=principal.user.id, status="draft", content="")
    db.add(unit)
    db.flush()
    apply_grants(db, principal, unit, body.grants)
    version = service.new_version(db, unit, principal, body.content, snapshot_from_input(body, unit))
    task = enqueue(db, principal, unit, version)
    service.emit_change(db, unit, "unit.created", version_id=version.id)
    audit(db, principal, "knowledge:create", unit.id, version_id=version.id)
    db.flush()
    return {**service.unit_view(db, unit, principal, detail=True), "task_id": task.id, "batch_id": task.batch_id}


@router.delete("/units")
def delete_units(body: s.UnitDelete, db: Db, principal: Delete):
    # Acquire deterministically and validate the full batch before any mutation.
    units = [accessible_unit(db, uid, principal, operation="knowledge:delete", lock=True)
             for uid in sorted(set(body.unit_ids))]
    for unit in units:
        unit.status = "deleted"
        unit.updated_at = m.utcnow()
        service.emit_change(db, unit, "unit.deleted")
        audit(db, principal, "knowledge:delete", unit.id)
    return {"deleted_unit_ids": [u.id for u in units], "message": f"已删除 {len(units)} 篇知识"}


@router.get("/units/{unit_id}")
def detail(unit_id: str, db: Db, principal: Read):
    return service.unit_view(db, accessible_unit(db, unit_id, principal), principal, detail=True)


@router.put("/units/{unit_id}")
def update_unit(unit_id: str, body: s.UnitInput, db: Db, principal: Edit):
    unit = accessible_unit(db, unit_id, principal, operation="knowledge:update", lock=True)
    if not body.content.strip():
        raise HTTPException(422, "正文不能为空")
    apply_grants(db, principal, unit, body.grants)
    snapshot = snapshot_from_input(body, unit)
    previous_version = service.latest_version(db, unit)
    version = service.new_version(db, unit, principal, body.content, snapshot)
    inherit_attachments(db, principal, unit, previous_version, version)
    task = enqueue(db, principal, unit, version)
    # Drafts without an active version can show their current title in management search.
    if not unit.active_version_id:
        for key in ("title", "summary", "category"):
            setattr(unit, key, snapshot[key])
        unit.tags_json = snapshot["tags"]
    unit.updated_at = m.utcnow()
    service.emit_change(db, unit, "unit.version.created", version_id=version.id)
    audit(db, principal, "knowledge:update", unit.id, version_id=version.id)
    db.flush()
    return {**service.unit_view(db, unit, principal, detail=True), "task_id": task.id, "batch_id": task.batch_id}


@router.post("/units/{unit_id}/status")
def set_status(unit_id: str, body: s.UnitStatus, db: Db, principal: Edit):
    unit = accessible_unit(db, unit_id, principal, operation="knowledge:update", lock=True)
    if body.status == "published":
        active = db.get(m.KnowledgeVersion, unit.active_version_id) if unit.active_version_id else None
        if not active or active.unit_id != unit.id or active.status != "ready":
            raise HTTPException(409, "请先等待索引完成并激活一个可用版本")
    if unit.status != body.status:
        previous = unit.status
        unit.status = body.status
        unit.updated_at = m.utcnow()
        service.emit_change(db, unit, "unit.status.changed", previous_status=previous)
        audit(db, principal, "knowledge:status", unit.id, status=body.status)
    db.flush()
    return service.unit_view(db, unit, principal, detail=True)


@router.get("/units/{unit_id}/versions")
def versions(unit_id: str, db: Db, principal: Read):
    unit = accessible_unit(db, unit_id, principal, operation="knowledge:update")
    rows = db.scalars(select(m.KnowledgeVersion).where(m.KnowledgeVersion.unit_id == unit.id)
                      .order_by(m.KnowledgeVersion.version_number.desc()))
    return {"items": [service.version_view(v, unit, db) for v in rows]}


@router.get("/units/{unit_id}/versions/{version_id}")
def version_detail(unit_id: str, version_id: str, db: Db, principal: Read):
    unit = accessible_unit(db, unit_id, principal, operation="knowledge:update")
    version = version_record(db, unit, version_id)
    chunks = db.scalars(select(m.KnowledgeChunk).where(m.KnowledgeChunk.version_id == version.id)
                        .order_by(m.KnowledgeChunk.chunk_index))
    files = db.scalars(select(m.StoredFile).where(m.StoredFile.unit_id == unit.id, m.StoredFile.version_id == version.id))
    return {**service.version_view(version, unit, db), "content": version.content,
            "chunks": [{"id": c.id, "chunk_id": c.id, "unit_id": c.unit_id, "version_id": c.version_id,
                        "chunk_index": c.chunk_index, "content": c.content, "position": c.position_json} for c in chunks],
            "attachments": [service.file_view(f) for f in files]}


@router.post("/units/{unit_id}/versions/{version_id}/activate")
def activate(unit_id: str, version_id: str, db: Db, principal: Edit):
    unit = accessible_unit(db, unit_id, principal, operation="knowledge:update", lock=True)
    version = version_record(db, unit, version_id)
    service.activate_version(db, unit, version)
    audit(db, principal, "knowledge:activate", unit.id, version_id=version.id)
    db.flush()
    return service.unit_view(db, unit, principal, detail=True)


@router.post("/units/{unit_id}/versions/{version_id}/rebuild", status_code=202)
def rebuild(unit_id: str, version_id: str, db: Db, principal: Edit):
    unit = accessible_unit(db, unit_id, principal, operation="knowledge:update", lock=True)
    source = version_record(db, unit, version_id)
    version = service.new_version(db, unit, principal, source.content, dict(source.metadata_json or service.metadata(unit)))
    inherit_attachments(db, principal, unit, source, version)
    task = enqueue(db, principal, unit, version)
    unit.updated_at = m.utcnow()
    service.emit_change(db, unit, "unit.version.created", version_id=version.id, rebuilt_from=source.id)
    audit(db, principal, "knowledge:rebuild", unit.id, version_id=version.id)
    db.flush()
    return {**service.unit_view(db, unit, principal, detail=True), "task_id": task.id, "batch_id": task.batch_id}


def storage():
    from atguigu.business.import_service import get_storage
    return get_storage()


def image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.post("/units/{unit_id}/attachments", status_code=201)
async def add_attachment(unit_id: str, db: Db, principal: Edit, file: UploadFile = File(...),
                         version_id: str | None = Form(None)):
    unit = accessible_unit(db, unit_id, principal, operation="knowledge:update", lock=True)
    version = version_record(db, unit, version_id) if version_id else service.latest_version(db, unit)
    if not version:
        raise HTTPException(409, "请先创建知识版本")
    data = await file.read(20 * 1024 * 1024 + 1)
    await file.close()
    if not data or len(data) > 20 * 1024 * 1024:
        raise HTTPException(422, "附件不能为空且不得超过 20 MB")
    name = PurePosixPath((file.filename or "attachment").replace("\\", "/")).name
    name = "".join(c for c in name if ord(c) >= 32)[:255] or "attachment"
    media_type = image_type(data) or "application/octet-stream"
    key = f"units/{unit.id}/versions/{version.id}/attachments/{uuid4().hex}"
    try:
        client = storage()
        client.put_bytes(key, data, content_type=media_type)
    except Exception:
        raise HTTPException(503, "附件存储暂不可用，请稍后重试") from None
    record = m.StoredFile(owner_id=principal.user.id, unit_id=unit.id, version_id=version.id,
                           file_name=name, object_key=key, bucket=client.bucket, purpose="attachment",
                           content_type=media_type, file_size=len(data), sha256=sha256(data).hexdigest())
    db.add(record)
    db.flush()
    service.emit_change(db, unit, "unit.attachment.changed", version_id=version.id, file_id=record.id)
    return service.file_view(record)


@router.delete("/units/{unit_id}/attachments/{file_id}")
def delete_attachment(unit_id: str, file_id: str, db: Db, principal: Edit):
    unit = accessible_unit(db, unit_id, principal, operation="knowledge:update", lock=True)
    record = db.get(m.StoredFile, file_id)
    if not record or record.unit_id != unit.id or record.purpose != "attachment":
        raise HTTPException(404, "附件不存在或不可删除")
    service.emit_change(db, unit, "unit.attachment.deleted", version_id=record.version_id, file_id=record.id,
                        storage_cleanup={"bucket": record.bucket, "object_key": record.object_key})
    db.delete(record)
    return {"message": "附件已删除"}


def file_response(db, principal, file_id, *, inline=False):
    record = accessible_file(db, file_id, principal)
    try:
        client = storage()
        data = client.get_bytes(record.object_key, bucket=record.bucket)
    except Exception:
        raise HTTPException(503, "文件存储暂不可用，请稍后重试") from None
    media_type = image_type(data) if inline else "application/octet-stream"
    if inline and not media_type:
        raise HTTPException(415, "此文件不是支持的图片")
    disposition = "inline" if inline else "attachment"
    return Response(content=data, media_type=media_type,
                    headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(record.file_name, safe='')}",
                             "Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache",
                             "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox"})


@router.get("/files/{file_id}/download")
def download(file_id: str, db: Db, principal: FileRead):
    return file_response(db, principal, file_id)


@router.get("/files/{file_id}/image")
def image(file_id: str, db: Db, principal: FileRead):
    return file_response(db, principal, file_id, inline=True)
