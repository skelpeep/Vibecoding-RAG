"""Authenticated organization and permission APIs. No RAG workflow is exposed here."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select

from atguigu.business import schemas as s
from atguigu.business.authorization import accessible_file, check_result, owned_record, owned_session
from atguigu.business.models import (
    AuditEvent, ChatSession, Department, ImportBatch, ImportTask, KnowledgeUnit, OutboxEvent,
    Permission, Role, RolePermission, UnitPermission, User, UserRole,
)
from atguigu.business.security import (
    Current, Db, DUMMY_HASH, Principal, hash_password, issue_token, load_principal, require, verify_password,
)
from atguigu.config.config import BusinessConfig

router = APIRouter(prefix="/api")


def audit(db, principal, action, resource_id, **details):
    db.add(AuditEvent(actor_id=principal.user.id, action=action, resource_id=resource_id, details_json=details))


def get_record(db, model, record_id, *, lock=False):
    query = select(model).where(model.id == record_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = db.scalar(query)
    if not record:
        raise HTTPException(404, "记录不存在")
    return record


def validate_department(db, department_id):
    if department_id:
        get_record(db, Department, department_id)


def validate_roles(db, role_ids):
    role_ids = set(role_ids)
    if set(db.scalars(select(Role.id).where(Role.id.in_(role_ids)))) != role_ids:
        raise HTTPException(422, "角色不存在")
    return role_ids


def user_view(db, user):
    department = db.get(Department, user.department_id) if user.department_id else None
    roles = db.scalars(select(Role).join(UserRole, Role.id == UserRole.role_id).where(UserRole.user_id == user.id).order_by(Role.role_code)).all()
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "email": user.email,
            "status": user.status, "department_id": user.department_id,
            "department": {"id": department.id, "name": department.name} if department else None,
            "roles": [{"id": role.id, "role_name": role.role_name, "role_code": role.role_code} for role in roles],
            "created_at": user.created_at.isoformat() + "Z", "updated_at": user.updated_at.isoformat() + "Z"}


def role_view(db, role):
    return {"id": role.id, "role_name": role.role_name, "role_code": role.role_code, "description": role.description,
            "permission_codes": sorted(db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id == role.id)))}


@router.post("/auth/login", tags=["认证"])
def login(body: s.Login, db: Db):
    user = db.scalar(select(User).where(User.username == body.username))
    valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not valid or not user or user.status != "active":
        raise HTTPException(401, "用户名或密码错误，或账号已停用", headers={"WWW-Authenticate": "Bearer"})
    principal = load_principal(db, user)
    return {"access_token": issue_token(user), "token_type": "bearer", "expires_in": BusinessConfig.jwt_minutes * 60,
            "user_info": user_view(db, user), "permissions": sorted(principal.permissions)}


@router.get("/auth/me", tags=["认证"])
def me(db: Db, principal: Current):
    return {"user_info": user_view(db, principal.user), "permissions": sorted(principal.permissions)}


@router.put("/auth/profile", tags=["认证"])
def profile(body: s.Profile, db: Db, principal: Current):
    user = get_record(db, User, principal.user.id, lock=True)
    user.display_name, user.email = body.display_name, body.email
    audit(db, principal, "auth:profile", user.id)
    db.flush()
    return user_view(db, user)


@router.post("/auth/password", tags=["认证"])
def password(body: s.ChangePassword, db: Db, principal: Current):
    user = get_record(db, User, principal.user.id, lock=True)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "当前密码不正确")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit(db, principal, "auth:password", user.id)
    return {"message": "密码已更新，请重新登录"}


@router.post("/auth/logout", tags=["认证"])
def logout(db: Db, principal: Current):
    user = get_record(db, User, principal.user.id, lock=True)
    user.token_version += 1
    return {"message": "已退出此账号的全部登录会话"}


@router.get("/auth/menus", tags=["认证"])
def menus(db: Db, principal: Current):
    records = db.scalars(select(Permission).where(Permission.permission_type == "menu", Permission.code.in_(principal.permissions)).order_by(Permission.sort_order)).all()
    return {"items": [{"code": item.code, "name": item.name, "path": item.path, "parent_code": item.parent_code} for item in records]}


@router.get("/org/permissions", tags=["组织"], dependencies=[Depends(require("org:role:read"))])
def permission_catalog(db: Db):
    rows = db.scalars(select(Permission).order_by(Permission.sort_order, Permission.code)).all()
    return {"items": [{"code": p.code, "name": p.name, "permission_type": p.permission_type,
                       "parent_code": p.parent_code, "path": p.path} for p in rows]}


@router.get("/org/users", tags=["组织"], dependencies=[Depends(require("org:user:read"))])
def users(db: Db, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
          search: str = Query("", max_length=100), department_id: str | None = Query(None, max_length=36),
          status: str | None = Query(None, pattern="^(active|disabled)$")):
    query = select(User)
    if search:
        query = query.where(User.username.contains(search, autoescape=True) | User.display_name.contains(search, autoescape=True))
    if department_id:
        query = query.where(User.department_id == department_id)
    if status:
        query = query.where(User.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(User.created_at, User.id).offset((page - 1) * page_size).limit(page_size))
    return {"items": [user_view(db, row) for row in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/org/users", tags=["组织"], status_code=201)
def create_user(body: s.UserCreate, db: Db, principal: Annotated[Principal, Depends(require("org:user:create"))]):
    validate_department(db, body.department_id)
    if body.role_ids and "org:user:assign-roles" not in principal.permissions:
        raise HTTPException(403, "缺少分配角色权限")
    role_ids = validate_roles(db, body.role_ids)
    user = User(**body.model_dump(exclude={"password", "role_ids"}), password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    db.add_all(UserRole(user_id=user.id, role_id=role_id) for role_id in role_ids)
    audit(db, principal, "org:user:create", user.id)
    db.flush()
    return user_view(db, user)


@router.put("/org/users/{user_id}", tags=["组织"])
def edit_user(user_id: str, body: s.UserEdit, db: Db, principal: Annotated[Principal, Depends(require("org:user:update"))]):
    validate_department(db, body.department_id)
    user = get_record(db, User, user_id, lock=True)
    for key, value in body.model_dump().items():
        setattr(user, key, value)
    audit(db, principal, "org:user:update", user.id)
    db.flush()
    return user_view(db, user)


@router.post("/org/users/{user_id}/roles", tags=["组织"])
def assign_roles(user_id: str, body: s.UserRoles, db: Db, principal: Annotated[Principal, Depends(require("org:user:assign-roles"))]):
    user = get_record(db, User, user_id, lock=True)
    role_ids = validate_roles(db, body.role_ids)
    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    db.add_all(UserRole(user_id=user.id, role_id=role_id) for role_id in role_ids)
    audit(db, principal, "org:user:assign-roles", user.id, role_ids=sorted(role_ids))
    db.flush()
    return user_view(db, user)


@router.post("/org/users/{user_id}/status", tags=["组织"])
def user_status(user_id: str, body: s.UserStatus, db: Db, principal: Annotated[Principal, Depends(require("org:user:status"))]):
    user = get_record(db, User, user_id, lock=True)
    if user.status != body.status:
        user.status = body.status
        user.token_version += 1
    audit(db, principal, "org:user:status", user.id, status=body.status)
    db.flush()
    return user_view(db, user)


@router.post("/org/users/{user_id}/reset-password", tags=["组织"])
def reset_password(user_id: str, body: s.ResetPassword, db: Db, principal: Annotated[Principal, Depends(require("org:user:reset-password"))]):
    user = get_record(db, User, user_id, lock=True)
    user.password_hash = hash_password(body.password)
    user.token_version += 1
    audit(db, principal, "org:user:reset-password", user.id)
    return {"message": "密码已重置，原登录已失效"}


@router.get("/org/roles", tags=["组织"], dependencies=[Depends(require("org:role:read"))])
def roles(db: Db):
    return {"items": [role_view(db, role) for role in db.scalars(select(Role).order_by(Role.role_code))]}


@router.post("/org/roles", tags=["组织"], status_code=201)
def create_role(body: s.RoleInput, db: Db, principal: Annotated[Principal, Depends(require("org:role:create"))]):
    role = Role(**body.model_dump())
    db.add(role)
    db.flush()
    audit(db, principal, "org:role:create", role.id)
    return role_view(db, role)


@router.put("/org/roles/{role_id}", tags=["组织"])
def edit_role(role_id: str, body: s.RoleInput, db: Db, principal: Annotated[Principal, Depends(require("org:role:update"))]):
    role = get_record(db, Role, role_id, lock=True)
    for key, value in body.model_dump().items():
        setattr(role, key, value)
    audit(db, principal, "org:role:update", role.id)
    db.flush()
    return role_view(db, role)


@router.post("/org/roles/{role_id}/permissions", tags=["组织"])
def role_permissions(role_id: str, body: s.RolePermissions, db: Db, principal: Annotated[Principal, Depends(require("org:role:permissions"))]):
    role = get_record(db, Role, role_id, lock=True)
    codes = set(body.permission_codes)
    permissions = db.scalars(select(Permission).where(Permission.code.in_(codes))).all()
    if {item.code for item in permissions} != codes:
        raise HTTPException(422, "权限编码不存在")
    db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    db.add_all(RolePermission(role_id=role.id, permission_code=item.code, permission_type=item.permission_type) for item in permissions)
    audit(db, principal, "org:role:permissions", role.id, permission_codes=sorted(codes))
    db.flush()
    return role_view(db, role)


@router.delete("/org/roles/{role_id}", tags=["组织"])
def delete_role(role_id: str, db: Db, principal: Annotated[Principal, Depends(require("org:role:delete"))]):
    role = get_record(db, Role, role_id, lock=True)
    referenced = db.scalar(select(UserRole.id).where(UserRole.role_id == role.id).limit(1)) or db.scalar(
        select(UnitPermission.id).where(UnitPermission.target_type == "role", UnitPermission.target_id == role.id).limit(1))
    if referenced:
        raise HTTPException(409, "角色仍有关联成员或知识授权，请先解除关联")
    audit(db, principal, "org:role:delete", role.id)
    db.delete(role)
    return {"message": "已删除"}


@router.get("/org/departments", tags=["组织"], dependencies=[Depends(require("org:department:read"))])
def departments(db: Db):
    rows = db.scalars(select(Department).order_by(Department.sort_order, Department.code)).all()
    counts = dict(db.execute(select(User.department_id, func.count(User.id)).group_by(User.department_id)).all())
    nodes = {d.id: {"id": d.id, "code": d.code, "name": d.name, "parent_id": d.parent_id,
                    "leader_id": d.leader_id, "sort_order": d.sort_order, "member_count": counts.get(d.id, 0), "children": []} for d in rows}
    roots = []
    for d in rows:
        (nodes[d.parent_id]["children"] if d.parent_id in nodes else roots).append(nodes[d.id])
    return {"items": roots}


def validate_tree(db, body, department_id=None):
    # Serialize hierarchy edits in a deterministic order to prevent concurrent A<->B cycles.
    rows = db.scalars(select(Department).order_by(Department.id).with_for_update().execution_options(populate_existing=True)).all()
    parents = {d.id: d.parent_id for d in rows}
    if body.parent_id and body.parent_id not in parents:
        raise HTTPException(422, "上级部门不存在")
    node, seen = body.parent_id, {department_id} if department_id else set()
    while node:
        if node in seen:
            raise HTTPException(422, "部门层级不能循环引用")
        seen.add(node)
        node = parents.get(node)
    if body.leader_id:
        leader = get_record(db, User, body.leader_id)
        if leader.status != "active":
            raise HTTPException(422, "负责人账号已停用")


@router.post("/org/departments", tags=["组织"], status_code=201)
def create_department(body: s.DepartmentInput, db: Db, principal: Annotated[Principal, Depends(require("org:department:create"))]):
    validate_tree(db, body)
    department = Department(**body.model_dump())
    db.add(department)
    db.flush()
    audit(db, principal, "org:department:create", department.id)
    return {"id": department.id, **body.model_dump()}


@router.put("/org/departments/{department_id}", tags=["组织"])
def edit_department(department_id: str, body: s.DepartmentInput, db: Db, principal: Annotated[Principal, Depends(require("org:department:update"))]):
    validate_tree(db, body, department_id)
    department = get_record(db, Department, department_id)
    for key, value in body.model_dump().items():
        setattr(department, key, value)
    audit(db, principal, "org:department:update", department.id)
    db.flush()
    return {"id": department.id, **body.model_dump()}


@router.delete("/org/departments/{department_id}", tags=["组织"])
def delete_department(department_id: str, db: Db, principal: Annotated[Principal, Depends(require("org:department:delete"))]):
    department = get_record(db, Department, department_id, lock=True)
    referenced = (db.scalar(select(Department.id).where(Department.parent_id == department.id).limit(1)) or
                  db.scalar(select(User.id).where(User.department_id == department.id).limit(1)) or
                  db.scalar(select(UnitPermission.id).where(UnitPermission.target_type == "department", UnitPermission.target_id == department.id).limit(1)))
    if referenced:
        raise HTTPException(409, "部门仍有下级、成员或知识授权，请先解除关联")
    audit(db, principal, "org:department:delete", department.id)
    db.delete(department)
    return {"message": "已删除"}


@router.post("/knowledge/check-permissions", tags=["知识权限"])
def check_permissions(body: s.PermissionCheck, db: Db, principal: Annotated[Principal, Depends(require("knowledge:check"))]):
    return check_result(db, principal, body.unit_ids)


@router.post("/knowledge/preview-permissions", tags=["知识权限"])
def preview_permissions(body: s.PermissionPreview, db: Db, principal: Annotated[Principal, Depends(require("knowledge:preview"))]):
    target = get_record(db, User, body.user_id)
    audit(db, principal, "knowledge:preview", target.id, unit_ids=body.unit_ids)
    return check_result(db, load_principal(db, target), body.unit_ids)


@router.get("/knowledge/units/{unit_id}/permissions", tags=["知识权限"], dependencies=[Depends(require("knowledge:permissions"))])
def get_grants(unit_id: str, db: Db):
    unit = get_record(db, KnowledgeUnit, unit_id)
    if unit.status == "deleted":
        raise HTTPException(404, "资源不存在或不可访问")
    return {"grants": [{"target_type": p.target_type, "target_id": p.target_id} for p in db.scalars(
        select(UnitPermission).where(UnitPermission.unit_id == unit_id).order_by(UnitPermission.target_type, UnitPermission.target_id))]}


@router.post("/knowledge/units/{unit_id}/permissions", tags=["知识权限"])
def set_grants(unit_id: str, body: s.Grants, db: Db, principal: Annotated[Principal, Depends(require("knowledge:permissions"))]):
    unit = get_record(db, KnowledgeUnit, unit_id, lock=True)
    if unit.status == "deleted":
        raise HTTPException(409, "知识已删除")
    grants = {(g.target_type, g.target_id) for g in body.grants}
    models = {"department": Department, "role": Role, "user": User}
    for kind, model in models.items():
        ids = {target for target_type, target in grants if target_type == kind}
        # Lock referenced entities against deletion during grant creation.
        if set(db.scalars(select(model.id).where(model.id.in_(ids)).with_for_update())) != ids:
            raise HTTPException(422, "授权实体不存在")
    db.execute(delete(UnitPermission).where(UnitPermission.unit_id == unit_id))
    db.add_all(UnitPermission(unit_id=unit_id, target_type=kind, target_id=target) for kind, target in sorted(grants))
    unit.permission_revision += 1
    db.add(OutboxEvent(event_type="unit.permissions.changed", aggregate_id=unit_id,
                       payload_json={"permission_revision": unit.permission_revision}))
    audit(db, principal, "knowledge:permissions", unit_id, grants=[list(g) for g in sorted(grants)])
    return {"unit_id": unit_id, "permission_revision": unit.permission_revision,
            "grants": [{"target_type": kind, "target_id": target} for kind, target in sorted(grants)]}


@router.post("/ai/sessions", tags=["归属"], status_code=201)
def create_session(body: s.SessionCreate, db: Db, principal: Annotated[Principal, Depends(require("ai:chat"))]):
    session = ChatSession(owner_id=principal.user.id, title=body.title)
    db.add(session)
    db.flush()
    return {"id": session.id, "title": session.title, "owner_id": session.owner_id}


@router.get("/ai/sessions", tags=["归属"])
def sessions(db: Db, principal: Annotated[Principal, Depends(require("ai:chat"))], page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    rows = db.scalars(select(ChatSession).where(ChatSession.owner_id == principal.user.id, ChatSession.status == "active").order_by(ChatSession.updated_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return {"items": [{"id": r.id, "title": r.title, "owner_id": r.owner_id} for r in rows]}


@router.get("/ai/sessions/{session_id}", tags=["归属"])
def session_info(session_id: str, db: Db, principal: Annotated[Principal, Depends(require("ai:chat"))]):
    record = owned_session(db, session_id, principal)
    return {"id": record.id, "title": record.title, "owner_id": record.owner_id}


@router.delete("/ai/sessions/{session_id}", tags=["归属"])
def delete_session(session_id: str, db: Db, principal: Annotated[Principal, Depends(require("ai:chat"))]):
    record = owned_session(db, session_id, principal)
    record.status = "deleted"
    return {"message": "已删除"}


@router.get("/knowledge/files/{file_id}", tags=["归属"])
def file_info(file_id: str, db: Db, principal: Annotated[Principal, Depends(require("knowledge:file:read"))]):
    record = accessible_file(db, file_id, principal)
    from atguigu.business.knowledge_service import file_view
    return file_view(record)
