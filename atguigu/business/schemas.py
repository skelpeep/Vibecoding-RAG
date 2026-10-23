from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=36)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: Code
    password: str = Field(min_length=1, max_length=128)


class Profile(Input):
    display_name: Name
    email: str | None = Field(default=None, max_length=254)


class ChangePassword(Input):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: Password


class ResetPassword(Input):
    password: Password


class UserCreate(Input):
    username: Code
    password: Password
    display_name: Name
    email: str | None = Field(default=None, max_length=254)
    department_id: Identifier | None = None
    role_ids: list[Identifier] = Field(default_factory=list, max_length=100)


class UserEdit(Input):
    display_name: Name
    email: str | None = Field(default=None, max_length=254)
    department_id: Identifier | None = None


class UserStatus(Input):
    status: Literal["active", "disabled"]


class UserRoles(Input):
    role_ids: list[Identifier] = Field(max_length=100)


class RoleInput(Input):
    role_name: Name
    role_code: Code
    description: str = Field(default="", max_length=500)


class RolePermissions(Input):
    permission_codes: list[Annotated[str, StringConstraints(min_length=1, max_length=100)]] = Field(max_length=200)


class DepartmentInput(Input):
    code: Code
    name: Name
    parent_id: Identifier | None = None
    leader_id: Identifier | None = None
    sort_order: int = Field(default=0, ge=0, le=100000)


class Grant(Input):
    target_type: Literal["global", "department", "role", "user"]
    target_id: Identifier

    @model_validator(mode="after")
    def global_id(self):
        if (self.target_type == "global") != (self.target_id == "*"):
            raise ValueError("global 的 target_id 必须为 *；其他实体须提供实际 ID")
        return self


class Grants(Input):
    grants: list[Grant] = Field(max_length=500)


class PermissionCheck(Input):
    unit_ids: list[Identifier] = Field(min_length=1, max_length=500)


class PermissionPreview(PermissionCheck):
    user_id: Identifier


class SessionCreate(Input):
    title: str = Field(default="新会话", min_length=1, max_length=200)
