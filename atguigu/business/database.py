"""Request-scoped transactions; timestamps and MySQL sessions always use UTC."""
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from atguigu.config.config import BusinessConfig, RuntimeConfig


def make_engine(url: str):
    options = {"pool_pre_ping": True, "hide_parameters": True}
    if url.startswith("mysql"):
        socket_timeout = max(5, int(RuntimeConfig.service_timeout))
        options.update(isolation_level="READ COMMITTED", connect_args={
            "connect_timeout": 5, "read_timeout": socket_timeout,
            "write_timeout": socket_timeout, "charset": "utf8mb4"})
    engine = create_engine(url, **options)
    if engine.dialect.name == "mysql":
        @event.listens_for(engine, "connect")
        def set_utc(connection, _):
            with connection.cursor() as cursor:
                cursor.execute("SET time_zone = '+00:00'")
    elif engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine


@lru_cache
def get_engine():
    return make_engine(BusinessConfig.mysql_url)


def get_db():
    with Session(get_engine(), expire_on_commit=False) as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
