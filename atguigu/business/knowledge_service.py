"""Knowledge views and version transitions shared by the management API.

Published metadata is copied only at activation. Neither a pending update nor an
indexing failure changes the active reader view.
"""
from hashlib import sha256

from fastapi import HTTPException
from sqlalchemy import func, select

from atguigu.business import models as m
from atguigu.business.authorization import can_manage_unit


def iso(value):
    return value.isoformat() + "Z" if value else None


def emit_change(db, unit, event_type, **details):
    db.add(m.OutboxEvent(event_type=event_type, aggregate_id=unit.id, payload_json={
        "unit_id": unit.id, "active_version_id": unit.active_version_id,
        "permission_revision": unit.permission_revision, "status": unit.status,
        "invalidate": ["knowledge", "retrieval", "faq"], **details,
    }))


def metadata(unit):
    return {"title": unit.title, "summary": unit.summary, "category": unit.category,
            "tags": list(unit.tags_json or []), "source_file_name": unit.source_file_name,
            "file_type": unit.file_type, "file_size": unit.file_size}


def latest_version(db, unit):
    return db.scalar(select(m.KnowledgeVersion).where(m.KnowledgeVersion.unit_id == unit.id)
                     .order_by(m.KnowledgeVersion.version_number.desc()).limit(1))


def version_view(version, unit, db=None):
    if not version:
        return None
    result = {"id": version.id, "version_id": version.id, "unit_id": version.unit_id,
            "version_number": version.version_number, "status": version.status,
            "content_hash": version.content_hash, "is_active": version.id == unit.active_version_id,
            "created_at": iso(version.created_at), "activated_at": iso(version.activated_at),
            "metadata": version.metadata_json or {}}
    if db is not None:
        task = db.scalar(select(m.ImportTask).where(m.ImportTask.version_id == version.id)
                         .order_by(m.ImportTask.created_at.desc()).limit(1))
        result.update(task_id=task.id if task else None, batch_id=task.batch_id if task else None)
    return result


def file_view(record):
    return {"id": record.id, "file_name": record.file_name, "file_size": record.file_size,
            "content_type": record.content_type, "purpose": record.purpose,
            "unit_id": record.unit_id, "version_id": record.version_id,
            "download_url": f"/api/knowledge/files/{record.id}/download",
            "image_url": f"/api/knowledge/files/{record.id}/image" if record.content_type in
            {"image/png", "image/jpeg", "image/gif", "image/webp"} else None}


def unit_view(db, unit, principal, *, detail=False):
    author = can_manage_unit(principal, unit)
    creator = db.get(m.User, unit.creator_id)
    grants = db.scalars(select(m.UnitPermission).where(m.UnitPermission.unit_id == unit.id)
                        .order_by(m.UnitPermission.target_type, m.UnitPermission.target_id)).all()
    counts = {kind: sum(g.target_type == kind for g in grants) for kind in ("global", "department", "role", "user")}
    result = {"id": unit.id, "unit_id": unit.id, "unit_code": unit.unit_code, **metadata(unit),
              "status": unit.status, "creator_id": unit.creator_id,
              "creator_name": creator.display_name if creator else "", "active_version_id": unit.active_version_id,
              "created_at": iso(unit.created_at), "updated_at": iso(unit.updated_at),
              "permission_revision": unit.permission_revision, "permission_summary": counts,
              "can_edit": can_manage_unit(principal, unit, "knowledge:update"),
              "can_delete": can_manage_unit(principal, unit, "knowledge:delete"),
              "can_manage_versions": can_manage_unit(principal, unit, "knowledge:update"),
              "can_attach": can_manage_unit(principal, unit, "knowledge:update"),
              "is_maintenance_view": author,
              "can_manage_permissions": "knowledge:permissions" in principal.permissions}
    if not detail:
        return result
    active = db.get(m.KnowledgeVersion, unit.active_version_id) if unit.active_version_id else None
    newest = latest_version(db, unit) if author else active
    visible_version = newest if author else active
    if author and newest and newest.metadata_json:
        result.update(newest.metadata_json)
    result.update(content=visible_version.content if visible_version else "",
                  active_version=version_view(active, unit, db if author else None),
                  latest_version=version_view(newest, unit, db if author else None),
                  grants=[{"target_type": g.target_type, "target_id": g.target_id} for g in grants]
                  if "knowledge:permissions" in principal.permissions else [])
    files = select(m.StoredFile).where(m.StoredFile.unit_id == unit.id)
    # Files remain tied to the displayed version; version detail exposes older files only to the author.
    files = files.where(m.StoredFile.version_id == visible_version.id) if visible_version else files.where(False)
    result["attachments"] = [file_view(f) for f in db.scalars(files.order_by(m.StoredFile.created_at, m.StoredFile.id))]
    return result


def new_version(db, unit, principal, content, snapshot):
    number = (db.scalar(select(func.max(m.KnowledgeVersion.version_number))
                        .where(m.KnowledgeVersion.unit_id == unit.id)) or 0) + 1
    version = m.KnowledgeVersion(unit_id=unit.id, version_number=number, creator_id=principal.user.id,
                                 content=content, content_hash=sha256(content.encode()).hexdigest(),
                                 metadata_json=snapshot, status="pending")
    db.add(version)
    db.flush()
    return version


def activate_version(db, unit, version):
    if version.unit_id != unit.id or version.status != "ready":
        raise HTTPException(409, "只有已完成索引的本知识版本可以激活")
    old_id = unit.active_version_id
    if old_id == version.id:
        return
    unit.active_version_id = version.id
    unit.content = version.content
    for key, value in (version.metadata_json or {}).items():
        if key in {"title", "summary", "category", "source_file_name", "file_type", "file_size"}:
            setattr(unit, key, value)
        elif key == "tags":
            unit.tags_json = list(value or [])
    version.activated_at = m.utcnow()
    unit.updated_at = m.utcnow()
    emit_change(db, unit, "unit.version.activated", previous_version_id=old_id, version_id=version.id)
