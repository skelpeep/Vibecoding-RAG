"""A unit uses OR across grants. Published access also needs a ready active version."""
from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from atguigu.business.models import (
    ChatSession, ImportBatch, ImportTask, KnowledgeUnit, KnowledgeVersion, StoredFile, UnitPermission,
)


def authorized_units(db, principal, unit_ids, *, published=True):
    if not unit_ids or principal.user.status != "active":
        return set()
    grant = or_(
        and_(UnitPermission.target_type == "global", UnitPermission.target_id == "*"),
        and_(UnitPermission.target_type == "user", UnitPermission.target_id == principal.user.id),
        and_(UnitPermission.target_type == "department", UnitPermission.target_id == principal.user.department_id)
        if principal.user.department_id else False,
        and_(UnitPermission.target_type == "role", UnitPermission.target_id.in_(principal.role_ids))
        if principal.role_ids else False,
    )
    query = select(KnowledgeUnit.id).join(UnitPermission, UnitPermission.unit_id == KnowledgeUnit.id).where(
        KnowledgeUnit.id.in_(unit_ids), grant, KnowledgeUnit.status != "deleted")
    if published:
        query = query.join(KnowledgeVersion, and_(KnowledgeVersion.id == KnowledgeUnit.active_version_id,
                                                 KnowledgeVersion.unit_id == KnowledgeUnit.id)).where(
            KnowledgeUnit.status == "published", KnowledgeVersion.status == "ready")
    return set(db.scalars(query.distinct()))


MANAGEMENT_PERMISSIONS = {"knowledge:create", "knowledge:update", "knowledge:import"}


def can_manage_unit(principal, unit, operation=None):
    """Explicit author maintenance, deliberately excluded from retrieval authorization."""
    return bool(principal.user.status == "active" and unit.status != "deleted"
                and unit.creator_id == principal.user.id
                and ((operation in principal.permissions) if operation else
                     (principal.permissions & MANAGEMENT_PERMISSIONS)))


def visible_unit_condition(principal):
    """SQL predicate applied before pagination/counting or searching sensitive titles."""
    grant = or_(
        and_(UnitPermission.target_type == "global", UnitPermission.target_id == "*"),
        and_(UnitPermission.target_type == "user", UnitPermission.target_id == principal.user.id),
        and_(UnitPermission.target_type == "department", UnitPermission.target_id == principal.user.department_id)
        if principal.user.department_id else False,
        and_(UnitPermission.target_type == "role", UnitPermission.target_id.in_(principal.role_ids))
        if principal.role_ids else False,
    )
    has_grant = select(UnitPermission.id).where(UnitPermission.unit_id == KnowledgeUnit.id, grant).exists()
    ready = select(KnowledgeVersion.id).where(KnowledgeVersion.unit_id == KnowledgeUnit.id,
                                            KnowledgeVersion.id == KnowledgeUnit.active_version_id,
                                            KnowledgeVersion.status == "ready").exists()
    reader = and_(KnowledgeUnit.status == "published", ready, has_grant)
    author = and_(KnowledgeUnit.creator_id == principal.user.id,
                  KnowledgeUnit.status != "deleted") if principal.permissions & MANAGEMENT_PERMISSIONS else False
    return or_(reader, author) if principal.user.status == "active" else False


def accessible_unit(db, unit_id, principal, *, operation=None, lock=False):
    query = select(KnowledgeUnit).where(KnowledgeUnit.id == unit_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    unit = db.scalar(query)
    if not unit or unit.status == "deleted":
        raise HTTPException(404, "资源不存在或不可访问")
    if operation:
        if not can_manage_unit(principal, unit, operation):
            raise HTTPException(404, "资源不存在或不可访问")
    elif not can_manage_unit(principal, unit) and unit.id not in authorized_units(db, principal, [unit.id]):
        raise HTTPException(404, "资源不存在或不可访问")
    return unit


def check_result(db, principal, ids):
    ids = list(dict.fromkeys(ids))
    allowed = authorized_units(db, principal, ids)
    return {"authorized_unit_ids": [i for i in ids if i in allowed],
            "unauthorized_unit_ids": [i for i in ids if i not in allowed]}


def owned_record(db, model, resource_id, principal, *, allow_task_admin=False):
    record = db.get(model, resource_id)
    can_audit_task = allow_task_admin and "knowledge:task:read-any" in principal.permissions
    if not record or (record.owner_id != principal.user.id and not can_audit_task):
        raise HTTPException(404, "资源不存在或不可访问")
    return record


def owned_session(db, resource_id, principal):
    record = owned_record(db, ChatSession, resource_id, principal)
    if record.status != "active":
        raise HTTPException(404, "资源不存在或不可访问")
    return record


def accessible_file(db, resource_id, principal):
    record = db.get(StoredFile, resource_id)
    if not record:
        raise HTTPException(404, "资源不存在或不可访问")
    if record.unit_id:
        unit = db.get(KnowledgeUnit, record.unit_id)
        if not unit or unit.status == "deleted":
            raise HTTPException(404, "资源不存在或不可访问")
        if not can_manage_unit(principal, unit):
            allowed = authorized_units(db, principal, [record.unit_id])
            if record.unit_id not in allowed or record.version_id != unit.active_version_id:
                raise HTTPException(404, "资源不存在或不可访问")
    elif record.owner_id != principal.user.id:
        raise HTTPException(404, "资源不存在或不可访问")
    return record
