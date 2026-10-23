"""Real independent-process MySQL/Mongo lease tests; no model inference claimed."""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business import chat_service as service
from atguigu.business.chat_history import get_history_store
from atguigu.business.models import ChatSession, QAAccessLog, User, utcnow
from atguigu.business.seed import seed_id


def claim(session_id):
    owner = seed_id('user/alice')
    with service.session_factory() as db:
        token_version = db.get(User, owner).token_version
    try:
        sid, rid = service.reserve(service.session_factory, get_history_store(), owner,
                                   token_version, '阶段五隔离租约测试，无模型调用', session_id)
        print(json.dumps({'accepted': True, 'session_id': sid, 'request_id': rid}))
    except HTTPException as exc:
        print(json.dumps({'accepted': False, 'status_code': exc.status_code}))


def main():
    owner = seed_id('user/alice')
    sid = str(uuid4())
    store = get_history_store()
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'session_id': sid,
              'method': 'real MySQL/Mongo independent subprocess CAS and controlled precise lease expiry',
              'model_calls': False, 'checks': [], 'passed': False}
    with service.session_factory() as db:
        db.add(ChatSession(id=sid, owner_id=owner, title='阶段五隔离租约验收', status='active'))
        db.commit()
    try:
        env = {**os.environ, 'PYTHONUTF8': '1'}
        args = [sys.executable, str(Path(__file__).resolve()), '--claim', sid]
        processes = [subprocess.Popen(args, cwd=ROOT, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, encoding='utf-8', env=env) for _ in range(2)]
        results = []
        for process in processes:
            output, errors = process.communicate(timeout=45)
            assert process.returncode == 0, errors[:200]
            results.append(json.loads(output.strip().splitlines()[-1]))
        assert sum(r['accepted'] for r in results) == 1, results
        assert next(r for r in results if not r['accepted'])['status_code'] == 409
        first = next(r['request_id'] for r in results if r['accepted'])
        report['claims'] = results
        report['checks'].append('two independent processes: exactly one reservation, second409')
        with service.session_factory() as db:
            row = db.get(ChatSession, sid)
            assert row.active_request_id == first
            assert len(list(db.scalars(select(QAAccessLog).where(QAAccessLog.session_id == sid)))) == 1
            # Expire only this exact QA session, never shift the database clock.
            row.lease_until = utcnow() - timedelta(seconds=1)
            db.commit()
        recovered = subprocess.run(args, cwd=ROOT, capture_output=True, text=True,
                                   encoding='utf-8', env=env, timeout=45)
        assert recovered.returncode == 0
        second = json.loads(recovered.stdout.strip().splitlines()[-1])
        assert second['accepted'] and second['request_id'] != first
        report['recovered'] = second
        with service.session_factory() as db:
            stale = db.get(QAAccessLog, first)
            assert stale.status == 'cancelled' and stale.details_json['reason'] == 'lease_expired'
        report['checks'].append('new process recovers expired session; old request persistent cancelled')
        before = store.get(owner, sid, first)
        stale_result = service.finalize(service.session_factory, store, owner, sid, first,
                                        status='completed', answer='stale QA injection must not persist')
        after = store.get(owner, sid, first)
        assert stale_result['status'] == 'cancelled'
        assert before == after
        with service.session_factory() as db:
            assert db.get(ChatSession, sid).active_request_id == second['request_id']
        report['checks'].append('stale finalize cannot overwrite Mongo nor release winner session')
        final = service.finalize(service.session_factory, store, owner, sid, second['request_id'],
                                 status='cancelled', reason='qa_cleanup')
        assert final['status'] == 'cancelled' and final['persisted']
        with service.session_factory() as db:
            row = db.get(ChatSession, sid)
            assert row.active_request_id is None and row.lease_until is None
        report['checks'].append('winner finalization acknowledges both stores and releases lease')
        report['passed'] = True
    finally:
        store.delete(owner, sid)
        with service.session_factory() as db:
            row = db.get(ChatSession, sid)
            row.status = 'deleted'
            row.active_request_id = None
            row.lease_until = None
            db.commit()
        report['mongo_cleanup'] = store.list(owner, sid) == []
        path = ROOT / 'docs/evidence/stage5/leases.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--claim':
        claim(sys.argv[2])
    else:
        main()
