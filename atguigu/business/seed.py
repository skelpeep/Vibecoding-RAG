"""Additive, deterministic demo seed. Existing accounts/roles are never reset."""
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from atguigu.business.catalog import PERMISSIONS, SYSTEM_ADMIN, KNOWLEDGE_ADMIN, ORDINARY
from atguigu.business.models import Department, Permission, Role, RolePermission, User, UserRole
from atguigu.business.security import hash_password


def seed_id(name):
    return str(uuid5(NAMESPACE_URL, "kb-platform/stage2/" + name))


DEPARTMENTS = [("demo-company", "示例组织", None), ("demo-tech", "技术部", "demo-company"),
               ("demo-sales", "销售部", "demo-company"), ("demo-dev", "研发组", "demo-tech")]
ROLES = [("system-admin", "系统管理员", SYSTEM_ADMIN), ("knowledge-admin", "知识管理员", KNOWLEDGE_ADMIN),
         ("employee", "普通用户", ORDINARY), ("engineer", "技术角色", ORDINARY), ("no-operation", "无操作权限测试角色", set())]
USERS = [("admin", "系统管理员（示例）", "demo-company", ["system-admin"], "active"),
         ("kb_admin", "知识管理员（示例）", "demo-tech", ["knowledge-admin"], "active"),
         ("alice", "技术部用户（示例）", "demo-tech", ["employee", "engineer"], "active"),
         ("bob", "销售部用户（示例）", "demo-sales", ["employee"], "active"),
         ("carol", "研发组用户（示例）", "demo-dev", ["employee"], "active"),
         ("disabled_demo", "停用账号（示例）", "demo-sales", ["employee"], "disabled"),
         ("no_op_demo", "无操作账号（示例）", "demo-sales", ["no-operation"], "active")]


def ensure_owned(db, model, key, value, expected_id):
    record = db.scalar(select(model).where(getattr(model, key) == value))
    if record and record.id != expected_id:
        raise ValueError(f"示例编码 {value} 已被其他记录使用，已取消初始化且未覆盖数据")
    return record


def seed_demo(db, passwords):
    created = []
    for entry in PERMISSIONS:
        if not db.get(Permission, entry["code"]):
            db.add(Permission(**entry))
            db.flush()  # Parent menu codes precede operations.
    for code, name, parent in DEPARTMENTS:
        record_id = seed_id("department/" + code)
        if not ensure_owned(db, Department, "code", code, record_id):
            db.add(Department(id=record_id, code=code, name=name,
                              parent_id=seed_id("department/" + parent) if parent else None))
            db.flush()
    for code, name, permissions in ROLES:
        record_id = seed_id("role/" + code)
        if not ensure_owned(db, Role, "role_code", code, record_id):
            db.add(Role(id=record_id, role_code=code, role_name=name, description="阶段二示例角色；可按业务调整"))
            db.flush()
            for permission_code in sorted(permissions):
                db.add(RolePermission(role_id=record_id, permission_code=permission_code,
                                      permission_type="menu" if permission_code.startswith("menu:") else "operation"))
            db.flush()
    for username, name, department, roles, status in USERS:
        record_id = seed_id("user/" + username)
        if not ensure_owned(db, User, "username", username, record_id):
            password = passwords[username]
            if len(password) < 12:
                raise ValueError("初始化密码至少 12 位")
            db.add(User(id=record_id, username=username, display_name=name, password_hash=hash_password(password),
                        department_id=seed_id("department/" + department), status=status))
            db.flush()
            db.add_all(UserRole(user_id=record_id, role_id=seed_id("role/" + role)) for role in roles)
            db.flush()
            created.append(username)
    return created
