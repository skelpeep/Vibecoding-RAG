"""Opt-in real MySQL multi-process lease evidence, without touching other queues.

KB_TEST_IMPORT_MYSQL=1 python -m pytest tests/test_stage4_import_mysql.py -q
Each dedicated-owner fixture is committed for independent connections and removed
afterward. Tasks are scheduled one hour ahead so ordinary live workers cannot take
them. Only subprocess test clocks advance; all locking/fencing is the actual worker.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, select, text
from sqlalchemy.orm import Session, with_loader_criteria

from atguigu.business import models as m
from atguigu.business.database import get_engine


def _child(owner_id, clock, command, task_id=None, token=None):
    from atguigu.business import import_worker as worker
    from atguigu.business.import_errors import LeaseLost
    worker.utcnow = lambda: datetime.fromisoformat(clock)
    @event.listens_for(Session, "do_orm_execute")
    def isolate_queue(execution):
        if execution.is_select:
            execution.statement = execution.statement.options(with_loader_criteria(m.ImportTask, m.ImportTask.owner_id == owner_id))
    if command == "claim":
        claimed = None
        # SKIP LOCKED is explicitly allowed to return an empty instantaneous view;
        # the production supervisor polls again once another short claim commits.
        for _ in range(20):
            claimed = worker.claim_next()
            if claimed:
                break
            time.sleep(0.1)
        print(json.dumps({"claimed": claimed}))
    elif command == "heartbeat":
        try:
            worker.heartbeat(task_id, token)
        except LeaseLost:
            print(json.dumps({"lease_lost": True}))
        else:
            print(json.dumps({"lease_lost": False}))
    elif command == "complete":
        try:
            worker.complete_task(task_id, token, "stale content", [], [])
        except LeaseLost:
            print(json.dumps({"lease_lost": True}))
        else:
            print(json.dumps({"lease_lost": False}))


def launch(owner_id, now, command="claim", task_id=None, token=None):
    arguments = [sys.executable, str(Path(__file__).resolve()), owner_id, now.isoformat(), command]
    if task_id:
        arguments.extend([task_id, token])
    environment = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=environment)


def result(process):
    stdout, stderr = process.communicate(timeout=30)
    assert process.returncode == 0, stderr[-1500:]
    return json.loads(stdout.strip().splitlines()[-1])


@pytest.fixture
def mysql_fixture():
    if os.getenv("KB_TEST_IMPORT_MYSQL") != "1":
        pytest.skip("Requires explicitly opted-in migrated real MySQL")
    engine = get_engine()
    assert engine.dialect.name == "mysql"
    owner_id, role_id = m.new_id(), m.new_id()
    batch_id = m.new_id()
    now = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    unit_ids, version_ids, task_ids, file_ids = [], [], [], []
    with Session(engine) as db, db.begin():
        assert db.get(m.Permission, "knowledge:import")
        db.add(m.User(id=owner_id, username="lease-" + uuid4().hex[:20], display_name="stage4 lease evidence", password_hash="not-a-login-hash"))
        db.add(m.Role(id=role_id, role_code="lease-" + uuid4().hex[:20], role_name="lease evidence")); db.flush()
        db.add(m.UserRole(user_id=owner_id, role_id=role_id))
        db.add(m.RolePermission(role_id=role_id, permission_code="knowledge:import", permission_type="operation"))
        db.add(m.ImportBatch(id=batch_id, owner_id=owner_id, idempotency_key="lease-evidence", file_count=3)); db.flush()
        for index in range(3):
            unit_id, version_id, file_id, task_id = [m.new_id() for _ in range(4)]
            unit_ids.append(unit_id); version_ids.append(version_id); file_ids.append(file_id); task_ids.append(task_id)
            db.add(m.KnowledgeUnit(id=unit_id, unit_code="lease-" + uuid4().hex, title="lease evidence", creator_id=owner_id)); db.flush()
            db.add(m.KnowledgeVersion(id=version_id, unit_id=unit_id, version_number=1, creator_id=owner_id)); db.flush()
            db.add(m.StoredFile(id=file_id, owner_id=owner_id, unit_id=unit_id, version_id=version_id,
                file_name="lease.txt", object_key="units/lease-evidence/" + uuid4().hex, bucket="not-used", sha256="0" * 64)); db.flush()
            db.add(m.ImportTask(id=task_id, owner_id=owner_id, batch_id=batch_id, unit_id=unit_id, version_id=version_id,
                file_id=file_id, idempotency_key=str(index), retry_at=now - timedelta(seconds=1),
                created_at=now - timedelta(minutes=3-index), progress_json={"operation": "knowledge:import"})); db.flush()
    try:
        yield engine, owner_id, now, task_ids
    finally:
        with Session(engine) as db, db.begin():
            db.execute(delete(m.ImportTask).where(m.ImportTask.owner_id == owner_id))
            db.execute(delete(m.ImportBatch).where(m.ImportBatch.owner_id == owner_id))
            db.execute(delete(m.StoredFile).where(m.StoredFile.owner_id == owner_id))
            db.execute(delete(m.KnowledgeVersion).where(m.KnowledgeVersion.id.in_(version_ids)))
            db.execute(delete(m.KnowledgeUnit).where(m.KnowledgeUnit.id.in_(unit_ids)))
            db.execute(delete(m.UserRole).where(m.UserRole.user_id == owner_id))
            db.execute(delete(m.RolePermission).where(m.RolePermission.role_id == role_id))
            db.execute(delete(m.Role).where(m.Role.id == role_id))
            db.execute(delete(m.User).where(m.User.id == owner_id))


def test_real_mysql_skip_locked_other_connection(mysql_fixture):
    engine, owner, now, task_ids = mysql_fixture
    with Session(engine) as locked, locked.begin():
        locked.scalar(select(m.ImportTask).where(m.ImportTask.id == task_ids[0]).with_for_update())
        first = result(launch(owner, now))["claimed"]
        assert first[0] == task_ids[1]
    second = result(launch(owner, now))["claimed"]
    assert second[0] == task_ids[0]


def test_real_mysql_two_processes_claim_different_tasks(mysql_fixture):
    engine, owner, now, task_ids = mysql_fixture
    first, second = launch(owner, now), launch(owner, now)
    claims = [result(first)["claimed"], result(second)["claimed"]]
    assert len({claim[0] for claim in claims}) == 2
    with Session(engine) as db:
        assert all(db.get(m.ImportTask, claim[0]).attempts == 1 for claim in claims)


def test_real_mysql_process_restart_lease_recovery_and_fencing(mysql_fixture):
    engine, owner, now, task_ids = mysql_fixture
    old = result(launch(owner, now))["claimed"]
    # The claiming OS process has exited. Force its persisted lease to expire.
    with Session(engine) as db, db.begin():
        db.get(m.ImportTask, old[0]).lease_until = now - timedelta(seconds=1)
    new = result(launch(owner, now))["claimed"]
    assert old[0] == new[0] and old[1] != new[1]
    assert result(launch(owner, now, "heartbeat", *old))["lease_lost"]
    assert result(launch(owner, now, "complete", *old))["lease_lost"]
    assert not result(launch(owner, now, "heartbeat", *new))["lease_lost"]
    with Session(engine) as db:
        task = db.get(m.ImportTask, new[0])
        assert task.attempts == 2 and task.worker_id == new[1] and task.status == "processing"
        assert db.get(m.KnowledgeVersion, task.version_id).content == ""


if __name__ == "__main__":
    _child(*sys.argv[1:])
