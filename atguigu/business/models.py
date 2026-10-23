"""Stage 2 schema. Later business workflows are deliberately not implemented here."""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON, BigInteger, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
    Index, Integer, MetaData, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ID = String(36)
BODY = Text().with_variant(LONGTEXT(), "mysql")


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id():
    return str(uuid4())


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


class Record:
    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Updated:
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Department(Record, Updated, Base):
    __tablename__ = "departments"
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), index=True)
    leader_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", use_alter=True, name="fk_departments_leader_id_users"))
    sort_order: Mapped[int] = mapped_column(default=0)
    __table_args__ = (CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_self_parent"),)


class User(Record, Updated, Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(254))
    department_id: Mapped[str | None] = mapped_column(ForeignKey("departments.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    token_version: Mapped[int] = mapped_column(default=1)
    __table_args__ = (CheckConstraint("status IN ('active','disabled')", name="status"),)


class Role(Record, Updated, Base):
    __tablename__ = "roles"
    role_name: Mapped[str] = mapped_column(String(100))
    role_code: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(500), default="")


class UserRole(Record, Base):
    __tablename__ = "user_roles"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)


class Permission(Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    permission_type: Mapped[str] = mapped_column(String(16))
    parent_code: Mapped[str | None] = mapped_column(ForeignKey("permissions.code"))
    path: Mapped[str | None] = mapped_column(String(150))
    sort_order: Mapped[int] = mapped_column(default=0)
    __table_args__ = (CheckConstraint("permission_type IN ('menu','operation')", name="type"),)


class RolePermission(Record, Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    permission_code: Mapped[str] = mapped_column(ForeignKey("permissions.code"))
    permission_type: Mapped[str] = mapped_column(String(16))
    __table_args__ = (UniqueConstraint("role_id", "permission_code"),)


class KnowledgeUnit(Record, Updated, Base):
    __tablename__ = "knowledge_units"
    unit_code: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(BODY, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    tags_json: Mapped[list] = mapped_column(JSON, default=list)
    source_file_name: Mapped[str | None] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(20))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    active_version_id: Mapped[str | None] = mapped_column(ID)
    permission_revision: Mapped[int] = mapped_column(default=0)
    __table_args__ = (
        CheckConstraint("status IN ('draft','published','disabled','deleted')", name="status"),
        ForeignKeyConstraint(["id", "active_version_id"], ["knowledge_versions.unit_id", "knowledge_versions.id"],
                             use_alter=True, name="fk_knowledge_units_active_version"),
    )


class KnowledgeVersion(Record, Updated, Base):
    __tablename__ = "knowledge_versions"
    unit_id: Mapped[str] = mapped_column(ForeignKey("knowledge_units.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(BODY, default="")
    content_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("unit_id", "version_number", name="uq_versions_unit_number"),
        UniqueConstraint("unit_id", "id", name="uq_versions_unit_id"),
        CheckConstraint("status IN ('pending','indexing','ready','failed','retired')", name="status"),
    )


class KnowledgeChunk(Record, Base):
    __tablename__ = "knowledge_chunks"
    unit_id: Mapped[str] = mapped_column(ID, index=True)
    version_id: Mapped[str] = mapped_column(ID, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(BODY)
    position_json: Mapped[dict] = mapped_column(JSON, default=dict)
    vector_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    __table_args__ = (
        ForeignKeyConstraint(["unit_id", "version_id"], ["knowledge_versions.unit_id", "knowledge_versions.id"]),
        UniqueConstraint("version_id", "chunk_index"),
    )


class UnitPermission(Record, Base):
    __tablename__ = "unit_permissions"
    unit_id: Mapped[str] = mapped_column(ForeignKey("knowledge_units.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(ID)
    __table_args__ = (
        UniqueConstraint("unit_id", "target_type", "target_id"),
        CheckConstraint("target_type IN ('global','department','role','user')", name="target_type"),
        CheckConstraint("(target_type = 'global' AND target_id = '*') OR (target_type <> 'global' AND target_id <> '*')", name="target_id"),
        Index("ix_unit_permissions_target", "target_type", "target_id"),
    )


class StoredFile(Record, Base):
    __tablename__ = "stored_files"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_units.id"), index=True)
    version_id: Mapped[str | None] = mapped_column(ID)
    file_name: Mapped[str] = mapped_column(String(255))
    object_key: Mapped[str] = mapped_column(String(512), unique=True)
    bucket: Mapped[str] = mapped_column(String(63))
    purpose: Mapped[str] = mapped_column(String(20), default="source")
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_stored_files_id_owner"),
        CheckConstraint("version_id IS NULL OR unit_id IS NOT NULL", name="version_unit"),
        ForeignKeyConstraint(["unit_id", "version_id"], ["knowledge_versions.unit_id", "knowledge_versions.id"]),
    )


class ImportBatch(Record, Updated, Base):
    __tablename__ = "import_batches"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    file_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key"), UniqueConstraint("id", "owner_id"))


class ImportTask(Record, Updated, Base):
    __tablename__ = "import_tasks"
    batch_id: Mapped[str] = mapped_column(ID, index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    unit_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_units.id"))
    version_id: Mapped[str | None] = mapped_column(ID)
    file_id: Mapped[str] = mapped_column(ID)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    stage: Mapped[str] = mapped_column(String(64), default="uploaded")
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    worker_id: Mapped[str | None] = mapped_column(String(100))
    progress_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        ForeignKeyConstraint(["batch_id", "owner_id"], ["import_batches.id", "import_batches.owner_id"]),
        ForeignKeyConstraint(["file_id", "owner_id"], ["stored_files.id", "stored_files.owner_id"]),
        ForeignKeyConstraint(["unit_id", "version_id"], ["knowledge_versions.unit_id", "knowledge_versions.id"]),
        CheckConstraint("version_id IS NULL OR unit_id IS NOT NULL", name="version_unit"),
        CheckConstraint("status IN ('pending','processing','completed','failed','cancelled')", name="status"),
        UniqueConstraint("batch_id", "idempotency_key"), Index("ix_import_tasks_claim", "status", "retry_at", "lease_until"),
    )


class ChatSession(Record, Updated, Base):
    __tablename__ = "chat_sessions"
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="新会话")
    status: Mapped[str] = mapped_column(String(16), default="active")
    active_request_id: Mapped[str | None] = mapped_column(ID)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (UniqueConstraint("id", "owner_id"),)


class QAAccessLog(Record, Base):
    __tablename__ = "qa_access_logs"
    session_id: Mapped[str] = mapped_column(ID, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(BODY)
    recalled_unit_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    authorized_unit_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    unauthorized_unit_ids_json: Mapped[list] = mapped_column(JSON, default=list)
    cited_sources_json: Mapped[list] = mapped_column(JSON, default=list)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    model_usage_json: Mapped[dict] = mapped_column(JSON, default=dict)
    response_time_ms: Mapped[int | None] = mapped_column(Integer)
    first_token_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="processing")
    cache_status: Mapped[str] = mapped_column(String(16), default="miss")
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        ForeignKeyConstraint(["session_id", "user_id"], ["chat_sessions.id", "chat_sessions.owner_id"]),
        Index("ix_qa_access_logs_created_at", "created_at"),
    )


class FAQ(Record, Updated, Base):
    __tablename__ = "faqs"
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(BODY)
    category: Mapped[str] = mapped_column(String(100), default="")
    related_unit_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_units.id"))
    source_type: Mapped[str] = mapped_column(String(20), default="manual")
    status: Mapped[str] = mapped_column(String(20), default="pending_review", index=True)
    hit_count: Mapped[int] = mapped_column(default=0)
    frequency: Mapped[int] = mapped_column(default=0)
    fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True)
    revision: Mapped[int] = mapped_column(default=1)
    reviewer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    provenance_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (CheckConstraint("status IN ('pending_review','published','rejected','withdrawn')", name="status"),)


class FAQSource(Record, Base):
    __tablename__ = "faq_sources"
    faq_id: Mapped[str] = mapped_column(ForeignKey("faqs.id", ondelete="CASCADE"), index=True)
    unit_id: Mapped[str] = mapped_column(ID)
    version_id: Mapped[str] = mapped_column(ID)
    __table_args__ = (
        ForeignKeyConstraint(["unit_id", "version_id"], ["knowledge_versions.unit_id", "knowledge_versions.id"]),
        UniqueConstraint("faq_id", "unit_id", "version_id"),
    )


class KnowledgeGap(Record, Updated, Base):
    __tablename__ = "knowledge_gaps"
    question_pattern: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True)
    sample_questions_json: Mapped[list] = mapped_column(JSON, default=list)
    ask_count: Mapped[int] = mapped_column(default=0)
    last_asked_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="unresolved")
    resolved_unit_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge_units.id"))
    resolution_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (CheckConstraint("status IN ('unresolved','resolved','ignored')", name="status"),)


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(100))
    details_json: Mapped[dict] = mapped_column(JSON, default=dict)


class OutboxEvent(Record, Base):
    __tablename__ = "outbox_events"
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[str] = mapped_column(ID)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
