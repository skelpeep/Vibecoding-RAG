"""FAQ provenance and verified knowledge-gap resolution, retaining existing rows."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = depends_on = None


def upgrade():
    for table, column in (("faqs", "provenance_json"), ("knowledge_gaps", "resolution_json")):
        op.add_column(table, sa.Column(column, sa.JSON(), nullable=True))
        target = sa.table(table, sa.column(column, sa.JSON()))
        op.get_bind().execute(target.update().values({column: {}}))
        with op.batch_alter_table(table) as batch:
            batch.alter_column(column, existing_type=sa.JSON(), nullable=False)


def downgrade():
    op.drop_column("knowledge_gaps", "resolution_json")
    op.drop_column("faqs", "provenance_json")
