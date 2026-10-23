"""Versioned title, category, tags and source metadata.

Downgrade drops historical metadata snapshots; content/version rows remain intact.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable addition followed by backfill avoids JSON server-default restrictions
    # on supported MySQL installations. ORM writes always supply this field.
    op.add_column("knowledge_versions", sa.Column("metadata_json", sa.JSON(), nullable=True))
    connection = op.get_bind()
    versions = sa.table("knowledge_versions", sa.column("id", sa.String()),
                        sa.column("unit_id", sa.String()), sa.column("metadata_json", sa.JSON()))
    units = sa.table("knowledge_units", sa.column("id", sa.String()),
                     sa.column("title", sa.String()), sa.column("summary", sa.Text()),
                     sa.column("category", sa.String()), sa.column("tags_json", sa.JSON()),
                     sa.column("source_file_name", sa.String()), sa.column("file_type", sa.String()),
                     sa.column("file_size", sa.BigInteger()))
    for unit in connection.execute(sa.select(units)).mappings():
        snapshot = {key: unit[key] for key in ("title", "summary", "category", "source_file_name", "file_type", "file_size")}
        snapshot["tags"] = unit["tags_json"] or []
        connection.execute(versions.update().where(versions.c.unit_id == unit["id"]).values(metadata_json=snapshot))
    with op.batch_alter_table("knowledge_versions") as batch:
        batch.alter_column("metadata_json", existing_type=sa.JSON(), nullable=False)


def downgrade():
    with op.batch_alter_table("knowledge_versions") as batch:
        batch.drop_column("metadata_json")
