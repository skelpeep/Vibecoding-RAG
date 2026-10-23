"""Strict stage-four inputs. Ownership and version identifiers are server-assigned."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from atguigu.business.schemas import Grant, Identifier, Input

Tag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class UnitInput(Input):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    content: str = Field(min_length=1, max_length=2_000_000)
    summary: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=100)
    tags: list[Tag] = Field(default_factory=list, max_length=30)
    grants: list[Grant] | None = Field(default=None, max_length=500)


class UnitStatus(Input):
    status: Literal["draft", "published", "disabled"]


class UnitDelete(Input):
    unit_ids: list[Identifier] = Field(min_length=1, max_length=100)
