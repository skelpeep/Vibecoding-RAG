"""Stable permission codes. Menus never imply operation or content permissions."""

MENUS = [
    ("menu:org", "组织管理", "/org"),
    ("menu:knowledge", "知识维护", "/knowledge"),
    ("menu:ai", "AI 问答", "/chat"),
    ("menu:dashboard", "数据看板", "/dashboard"),
    ("menu:settlement", "知识沉淀", "/settlement"),
]
OPERATIONS = {
    "org": {
        "user:read": "查看用户", "user:create": "新增用户", "user:update": "编辑用户",
        "user:status": "启停账号", "user:reset-password": "重置密码", "user:assign-roles": "分配用户角色",
        "role:read": "查看角色", "role:create": "新增角色", "role:update": "编辑角色",
        "role:delete": "删除角色", "role:permissions": "配置角色权限",
        "department:read": "查看部门", "department:create": "新增部门", "department:update": "编辑部门",
        "department:delete": "删除部门",
    },
    "knowledge": {
        "read": "读取知识", "create": "新增知识", "update": "编辑知识", "delete": "删除知识",
        "import": "导入知识", "permissions": "配置知识授权", "check": "检查自己的知识权限",
        "preview": "代查用户知识权限", "file:read": "读取文件", "task:read": "读取自己的导入任务",
        "task:read-any": "代查导入任务元数据",
    },
    "ai": {"chat": "使用 AI 问答"},
    "dashboard": {"read": "查看统计"},
    "settlement": {"faq:read": "查看 FAQ", "faq:review": "审核 FAQ", "faq:publish": "发布 FAQ", "gap:manage": "管理知识缺口"},
}
PERMISSIONS = [dict(code=code, name=name, permission_type="menu", parent_code=None, path=path, sort_order=i)
               for i, (code, name, path) in enumerate(MENUS)]
for group, operations in OPERATIONS.items():
    PERMISSIONS.extend(dict(code=f"{group}:{code}", name=name, permission_type="operation",
                            parent_code=f"menu:{group}", path=None, sort_order=i)
                       for i, (code, name) in enumerate(operations.items()))

ORDINARY = {"menu:ai", "ai:chat", "knowledge:read", "knowledge:check", "knowledge:file:read"}
SYSTEM_ADMIN = {p["code"] for p in PERMISSIONS if p["code"].startswith(("org:", "dashboard:"))} | {
    "menu:org", "menu:dashboard", "knowledge:preview", "knowledge:task:read-any",
} | ORDINARY
KNOWLEDGE_ADMIN = {p["code"] for p in PERMISSIONS if p["code"].startswith(("knowledge:", "settlement:"))} | {
    "menu:knowledge", "menu:settlement",
} | ORDINARY
KNOWLEDGE_ADMIN.discard("knowledge:task:read-any")
