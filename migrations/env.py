from alembic import context
from atguigu.business.database import get_engine
from atguigu.business.models import Base
from atguigu.config.config import BusinessConfig

if context.is_offline_mode():
    context.configure(url=BusinessConfig.mysql_url, target_metadata=Base.metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
