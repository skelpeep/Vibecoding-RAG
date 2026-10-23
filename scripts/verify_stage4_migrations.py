"""Run 0001-0003 on isolated prefixed MySQL tables, including real 0003 backfill.

Only SQL identifiers are translated. The actual migration module is executed in
an Alembic online context; existing application tables are never altered.
"""
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, inspect, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business.database import get_engine
from atguigu.business.models import Base
from scripts.verify_stage2_migrations import render


def main():
    engine = get_engine()
    assert engine.dialect.name == "mysql"
    prefix = "s4v_" + uuid4().hex[:8] + "_"
    up, down = render("up"), render("down")
    names = set(Base.metadata.tables) | {"alembic_version"}
    names |= set(re.findall(r"\b(?:CONSTRAINT|INDEX)\s+`?([a-zA-Z_][a-zA-Z0-9_]*)", up + down))
    mapping = {name: prefix + name[:40] + "_" + hashlib.sha256(name.encode()).hexdigest()[:6] for name in names}
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r")\b")
    def translate(sql):
        return pattern.sub(lambda match: mapping[match[0]], sql)
    def statements(sql):
        return [translate(part).strip() for part in re.sub(r"(?m)^--.*$", "", sql).split(";") if part.strip()]
    tables = {mapping[name] for name in Base.metadata.tables} | {mapping["alembic_version"]}
    report = {"captured_at_utc": datetime.now(timezone.utc).isoformat(), "prefix": prefix, "passed": False,
              "method": "real MySQL isolated identifiers; actual online 0003 upgrade/downgrade"}
    migration_path = next((ROOT / "migrations/versions").glob("0003*.py"))
    spec = importlib.util.spec_from_file_location("stage4_migration_check", migration_path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    try:
        with engine.begin() as connection:
            assert not tables & set(inspect(connection).get_table_names())
            for sql in statements(up):
                connection.exec_driver_sql(sql)
            context = MigrationContext.configure(connection)
            def intercept(conn, cursor, statement, parameters, context, many):
                return translate(statement), parameters
            # The first run proves an empty stage-two schema upgrades successfully.
            event.listen(connection, "before_cursor_execute", intercept, retval=True)
            with Operations.context(context):
                migration.upgrade(); migration.downgrade()
            event.remove(connection, "before_cursor_execute", intercept)
            report["fresh_0001_to_0003"] = True
            # Insert realistic pre-0003 rows to exercise data migration, not only DDL.
            user_id, unit_id, version_id = [str(uuid4()) for _ in range(3)]
            connection.execute(text(f"INSERT INTO `{mapping['users']}` (id, username, password_hash, display_name, status, token_version, created_at, updated_at) VALUES (:id, :name, 'test-only', 'migration evidence', 'active', 1, UTC_TIMESTAMP(), UTC_TIMESTAMP())"), {"id": user_id, "name": prefix})
            connection.execute(text(f"INSERT INTO `{mapping['knowledge_units']}` (id,unit_code,title,content,summary,category,tags_json,file_size,status,creator_id,permission_revision,created_at,updated_at) VALUES (:id,:code,'旧版标题','正文','摘要','流程',:tags,0,'draft',:owner,0,UTC_TIMESTAMP(),UTC_TIMESTAMP())"), {"id": unit_id, "code": prefix, "owner": user_id, "tags": json.dumps(["migration", "示例"])})
            connection.execute(text(f"INSERT INTO `{mapping['knowledge_versions']}` (id,unit_id,version_number,content,status,creator_id,created_at,updated_at) VALUES (:id,:unit,1,'旧版正文','ready',:owner,UTC_TIMESTAMP(),UTC_TIMESTAMP())"), {"id": version_id, "unit": unit_id, "owner": user_id})
            event.listen(connection, "before_cursor_execute", intercept, retval=True)
            with Operations.context(context):
                migration.upgrade()
            event.remove(connection, "before_cursor_execute", intercept)
            snapshot = connection.scalar(text(f"SELECT metadata_json FROM `{mapping['knowledge_versions']}` WHERE id=:id"), {"id": version_id})
            snapshot = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
            assert snapshot["title"] == "旧版标题" and snapshot["tags"] == ["migration", "示例"]
            report["existing_metadata_backfill"] = True
            event.listen(connection, "before_cursor_execute", intercept, retval=True)
            with Operations.context(context):
                migration.downgrade(); migration.upgrade()
            event.remove(connection, "before_cursor_execute", intercept)
            assert connection.scalar(text(f"SELECT content FROM `{mapping['knowledge_versions']}` WHERE id=:id"), {"id": version_id}) == "旧版正文"
            report["downgrade_reupgrade_preserves_content"] = True
            report["business_tables"] = len(Base.metadata.tables)
            report["passed"] = True
    finally:
        with engine.begin() as connection:
            remaining = tables & set(inspect(connection).get_table_names())
            for table in remaining:
                assert table.startswith(prefix)
                for fk in inspect(connection).get_foreign_keys(table):
                    assert fk["name"].startswith(prefix)
                    connection.exec_driver_sql(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{fk['name']}`")
            for table in remaining:
                connection.exec_driver_sql(f"DROP TABLE `{table}`")
            report["temporary_tables_remaining"] = len(tables & set(inspect(connection).get_table_names()))
            report["live_revision"] = connection.scalar(text("SELECT version_num FROM alembic_version"))
        (ROOT / "docs/evidence/stage4/migrations.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
