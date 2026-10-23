"""enforce import file ownership

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_unique_constraint('uq_stored_files_id_owner', 'stored_files', ['id', 'owner_id'])
    op.drop_constraint(op.f('fk_import_tasks_file_id_stored_files'), 'import_tasks', type_='foreignkey')
    op.create_foreign_key(op.f('fk_import_tasks_file_id_stored_files'), 'import_tasks', 'stored_files', ['file_id', 'owner_id'], ['id', 'owner_id'])


def downgrade():
    op.drop_constraint(op.f('fk_import_tasks_file_id_stored_files'), 'import_tasks', type_='foreignkey')
    op.create_foreign_key(op.f('fk_import_tasks_file_id_stored_files'), 'import_tasks', 'stored_files', ['file_id'], ['id'])
    op.drop_constraint('uq_stored_files_id_owner', 'stored_files', type_='unique')
