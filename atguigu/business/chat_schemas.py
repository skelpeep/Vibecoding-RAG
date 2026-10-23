from pydantic import BaseModel, ConfigDict, Field, field_validator
from atguigu.config.config import RagConfig


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatQuestion(StrictBody):
    question: str = Field(min_length=1, max_length=RagConfig.question_max_chars)
    session_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请输入问题")
        return value


class SessionCreate(StrictBody):
    title: str = Field(default="新会话", min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        return value.strip() or "新会话"
