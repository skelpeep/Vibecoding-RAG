from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import select
from sqlalchemy.orm import Session

from atguigu.business.database import get_db
from atguigu.business.models import User, Role, UserRole, RolePermission
from atguigu.config.config import BusinessConfig

password_hasher = PasswordHash.recommended()
DUMMY_HASH = password_hasher.hash("invalid-login-placeholder")
bearer = HTTPBearer(auto_error=False)
Db = Annotated[Session, Depends(get_db, scope="function")]


def jwt_secret():
    if len(BusinessConfig.jwt_secret.encode()) < 32:
        raise HTTPException(503, "请先运行 scripts/init_stage2.py 配置认证密钥")
    return BusinessConfig.jwt_secret


def hash_password(password):
    return password_hasher.hash(password)


def verify_password(password, hashed):
    try:
        return password_hasher.verify(password, hashed)
    except (UnknownHashError, ValueError):
        return False


@dataclass
class Principal:
    user: User
    role_ids: set[str]
    permissions: set[str]


def load_principal(db, user):
    role_ids = set(db.scalars(select(UserRole.role_id).join(Role, Role.id == UserRole.role_id).where(UserRole.user_id == user.id)))
    permissions = set(db.scalars(select(RolePermission.permission_code).where(RolePermission.role_id.in_(role_ids)))) if role_ids else set()
    return Principal(user, role_ids, permissions)


def issue_token(user):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": user.id, "ver": user.token_version, "iat": now, "nbf": now,
                       "exp": now + timedelta(minutes=BusinessConfig.jwt_minutes),
                       "iss": BusinessConfig.jwt_issuer, "aud": BusinessConfig.jwt_audience}, jwt_secret(), algorithm="HS256")


def current_user(db: Db, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    unauthorized = HTTPException(401, "请登录或重新登录", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise unauthorized
    try:
        payload = jwt.decode(credentials.credentials, jwt_secret(), algorithms=["HS256"],
                             issuer=BusinessConfig.jwt_issuer, audience=BusinessConfig.jwt_audience,
                             options={"require": ["sub", "ver", "exp", "iat", "nbf", "iss", "aud"]})
    except jwt.InvalidTokenError:
        raise unauthorized
    user = db.get(User, payload["sub"])
    if not user or user.status != "active" or user.token_version != payload["ver"]:
        raise unauthorized
    return load_principal(db, user)


Current = Annotated[Principal, Depends(current_user)]


def require(code):
    def check(principal: Current):
        if code not in principal.permissions:
            raise HTTPException(403, "缺少操作权限")
        return principal
    return check


def legacy_data_closed(principal: Current):
    raise HTTPException(410, "旧基线数据接口已关闭；请使用管理 API，导入与问答在后续阶段接入")
