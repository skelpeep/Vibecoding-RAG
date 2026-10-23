"""Exercise exact Alembic SQL on isolated, uniquely prefixed MySQL tables.

Uses the configured project database and never renames, clears or alters its real
tables. Prefix mapping changes only SQL identifiers; constraints/data types and
the migration order are preserved. Only this run's tables are removed afterward.
"""
import hashlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from atguigu.business.database import get_engine
from atguigu.business.models import Base


def render(direction):
    buffer = io.StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=buffer)
    if direction == "up":
        # This is the historical stage-two check. Stage four has an online
        # metadata backfill, exercised separately by verify_stage4_migrations.py.
        command.upgrade(config, "0002", sql=True)
    else:
        command.downgrade(config, "0002:base", sql=True)
    return buffer.getvalue()


def main():
    engine = get_engine()
    assert engine.dialect.name == "mysql", "This validation requires MySQL"
    prefix = "s2v_" + uuid4().hex[:8] + "_"
    up, down = render("up"), render("down")
    names = set(Base.metadata.tables) | {"alembic_version"}
    # MySQL FK and CHECK names have database scope; indexes are also mapped.
    names |= set(re.findall(r"\b(?:CONSTRAINT|INDEX)\s+`?([a-zA-Z_][a-zA-Z0-9_]*)", up + down))
    mapping = {name: prefix + name[:40] + "_" + hashlib.sha256(name.encode()).hexdigest()[:6] for name in names}
    pattern = re.compile(r"\b(" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")\b")

    def statements(sql):
        sql = re.sub(r"(?m)^--.*$", "", sql)
        return [pattern.sub(lambda match: mapping[match[0]], part).strip() for part in sql.split(";") if part.strip()]

    created_tables = {mapping[name] for name in Base.metadata.tables} | {mapping["alembic_version"]}
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "prefix": prefix,
              "method": "exact Alembic offline SQL with identifier-only prefix mapping", "passed": False}
    try:
        with engine.begin() as connection:
            assert not created_tables & set(inspect(connection).get_table_names())
            for sql in statements(up):
                connection.exec_driver_sql(sql)
            report["fresh_upgrade"] = True
            report["revision"] = connection.scalar(text(f"SELECT version_num FROM `{mapping['alembic_version']}`"))
            assert report["revision"] == "0002"
            report["business_table_count"] = len(created_tables) - 1
            for sql in statements(down):
                connection.exec_driver_sql(sql)
            assert not (created_tables - {mapping["alembic_version"]}) & set(inspect(connection).get_table_names())
            assert connection.scalar(text(f"SELECT COUNT(*) FROM `{mapping['alembic_version']}`")) == 0
            report["downgrade"] = True
            report["passed"] = True
    finally:
        # DDL is not transactional in MySQL. On failure remove only this run's
        # verified table names and constraints, with FK checks left enabled.
        with engine.begin() as connection:
            remaining = created_tables & set(inspect(connection).get_table_names())
            for table in remaining:
                assert table.startswith(prefix)
                for fk in inspect(connection).get_foreign_keys(table):
                    name = fk["name"]
                    assert name.startswith(prefix)
                    connection.exec_driver_sql(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{name}`")
            for table in remaining:
                connection.exec_driver_sql(f"DROP TABLE `{table}`")
            report["temporary_tables_remaining"] = len(created_tables & set(inspect(connection).get_table_names()))
        target = ROOT / "docs/evidence/stage2/migrations.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
