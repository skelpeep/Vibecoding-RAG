"""Execute fresh schema and 0003–0005 migrations using isolated MySQL identifiers."""
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
    assert engine.dialect.name == 'mysql'
    prefix = 's6v_' + uuid4().hex[:8] + '_'
    up, down = render('up'), render('down')
    names = set(Base.metadata.tables) | {'alembic_version'}
    names |= set(re.findall(r'\b(?:CONSTRAINT|INDEX)\s+`?([a-zA-Z_][a-zA-Z0-9_]*)', up + down))
    mapping = {name: prefix + name[:40] + '_' + hashlib.sha256(name.encode()).hexdigest()[:6] for name in names}
    pattern = re.compile(r'\b(' + '|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + r')\b')
    translate = lambda sql: pattern.sub(lambda match: mapping[match[0]], sql)
    tables = {mapping[n] for n in Base.metadata.tables} | {mapping['alembic_version']}
    migrations = []
    for rev in ['0003', '0004', '0005']:
        spec = importlib.util.spec_from_file_location('s6_check_' + rev,
            next((ROOT / 'migrations/versions').glob(rev + '*.py')))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        migrations.append(module)
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'prefix': prefix,
              'method': 'real MySQL identifier-isolated actual online migration modules', 'passed': False}
    try:
        with engine.begin() as connection:
            assert not tables & set(inspect(connection).get_table_names())
            for part in re.sub(r'(?m)^--.*$', '', up).split(';'):
                if part.strip():
                    connection.exec_driver_sql(translate(part.strip()))
            context = MigrationContext.configure(connection)
            def intercept(conn, cursor, statement, parameters, context, many):
                return translate(statement), parameters
            event.listen(connection, 'before_cursor_execute', intercept, retval=True)
            with Operations.context(context):
                migrations[0].upgrade()
                migrations[1].upgrade()
                migrations[2].upgrade()
            event.remove(connection, 'before_cursor_execute', intercept)
            report['fresh_0001_to_0005'] = True
            user_id, session_id, request_id = [str(uuid4()) for _ in range(3)]
            connection.execute(text(f"INSERT INTO `{mapping['users']}` (id,username,password_hash,display_name,status,token_version,created_at,updated_at) VALUES (:id,:name,'qa-only','migration QA','active',1,UTC_TIMESTAMP(),UTC_TIMESTAMP())"), {'id': user_id, 'name': prefix})
            connection.execute(text(f"INSERT INTO `{mapping['chat_sessions']}` (id,owner_id,title,status,created_at,updated_at) VALUES (:id,:owner,'migration QA','active',UTC_TIMESTAMP(),UTC_TIMESTAMP())"), {'id': session_id, 'owner': user_id})
            connection.execute(text(f"INSERT INTO `{mapping['qa_access_logs']}` (id,session_id,user_id,question,answer,recalled_unit_ids_json,authorized_unit_ids_json,unauthorized_unit_ids_json,cited_sources_json,model_usage_json,status,cache_status,cancel_requested,details_json,created_at) VALUES (:id,:sid,:owner,'migration question','retained answer','[]','[]','[]','[]','{{}}','completed','miss',0,'{{}}',UTC_TIMESTAMP())"), {'id': request_id, 'sid': session_id, 'owner': user_id})
            event.listen(connection, 'before_cursor_execute', intercept, retval=True)
            with Operations.context(context):
                migrations[2].downgrade()
                migrations[2].upgrade()
            event.remove(connection, 'before_cursor_execute', intercept)
            assert connection.scalar(text(f"SELECT answer FROM `{mapping['qa_access_logs']}` WHERE id=:id"), {'id': request_id}) == 'retained answer'
            value = connection.scalar(text(f"SELECT details_json FROM `{mapping['qa_access_logs']}` WHERE id=:id"), {'id': request_id})
            assert (json.loads(value) if isinstance(value, str) else value) == {}
            for table, column in [('faqs','provenance_json'), ('knowledge_gaps','resolution_json')]:
                assert column in {c['name'] for c in inspect(connection).get_columns(mapping[table])}
            report['downgrade_reupgrade_retains_log_answer'] = True
            connection.execute(text(f"UPDATE `{mapping['chat_sessions']}` SET active_request_id=:rid,lease_until=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 90 SECOND) WHERE id=:id"), {'rid': request_id, 'id': session_id})
            event.listen(connection, 'before_cursor_execute', intercept, retval=True)
            refused = False
            try:
                with Operations.context(context):
                    migrations[1].downgrade()
            except RuntimeError:
                refused = True
            finally:
                event.remove(connection, 'before_cursor_execute', intercept)
            assert refused
            report['active_lease_downgrade_refused'] = True
            report['business_tables'] = len(Base.metadata.tables)
            report['passed'] = True
    finally:
        with engine.begin() as connection:
            remaining = tables & set(inspect(connection).get_table_names())
            for table in remaining:
                assert table.startswith(prefix)
                for fk in inspect(connection).get_foreign_keys(table):
                    assert fk['name'].startswith(prefix)
                    connection.exec_driver_sql(f"ALTER TABLE `{table}` DROP FOREIGN KEY `{fk['name']}`")
            for table in remaining:
                connection.exec_driver_sql(f"DROP TABLE `{table}`")
            report['temporary_tables_remaining'] = len(tables & set(inspect(connection).get_table_names()))
            report['live_revision'] = connection.scalar(text('SELECT version_num FROM alembic_version'))
        path = ROOT / 'docs/evidence/stage6/migrations.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
