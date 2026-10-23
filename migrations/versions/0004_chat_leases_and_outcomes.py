"""Persistent chat reservation and outcome metadata; no additional business tables.

Downgrade requires quiescent chat workers and retains historical questions/answers.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chat_sessions", sa.Column("active_request_id", sa.String(36), nullable=True))
    op.add_column("chat_sessions", sa.Column("lease_until", sa.DateTime(), nullable=True))
    op.add_column("qa_access_logs", sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("qa_access_logs", sa.Column("finished_at", sa.DateTime(), nullable=True))
    op.add_column("qa_access_logs", sa.Column("details_json", sa.JSON(), nullable=True))
    logs = sa.table("qa_access_logs", sa.column("details_json", sa.JSON()))
    op.get_bind().execute(logs.update().values(details_json={}))
    with op.batch_alter_table("qa_access_logs") as batch:
        batch.alter_column("details_json", existing_type=sa.JSON(), nullable=False)


def downgrade():
    connection = op.get_bind()
    active = connection.scalar(sa.text("SELECT COUNT(*) FROM chat_sessions WHERE active_request_id IS NOT NULL AND lease_until > CURRENT_TIMESTAMP"))
    if active:
        raise RuntimeError("Stop active chat requests before downgrading")
    with op.batch_alter_table("qa_access_logs") as batch:
        batch.drop_column("details_json")
        batch.drop_column("finished_at")
        batch.drop_column("cancel_requested")
    with op.batch_alter_table("chat_sessions") as batch:
        batch.drop_column("lease_until")
        batch.drop_column("active_request_id")
