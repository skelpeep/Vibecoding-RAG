"""Close exact pre-fix/restart QA requests; never bulk-edit arbitrary processing logs."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business import chat_service as service
from atguigu.business.chat_history import get_history_store
from atguigu.business.models import ChatSession, QAAccessLog

# Recorded initial disconnect and explicitly interrupted browser QA sessions.
REQUESTS = {
    '1c5bf87a-7eeb-467c-8bee-3538c753d1e1': '194f8971-fdcd-4252-be21-796f18ba8d7f',
    'dd385974-3d59-4c09-955a-c401b451a2d6': '45545563-7082-47c0-b74d-ea2431f11464',
    'f29c1763-1c4e-47d2-8371-55bd12a2c512': 'a6e81fab-a394-436c-a670-7d7b330d0906',
}


def main():
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'closed': []}
    for rid, sid in REQUESTS.items():
        with service.session_factory() as db:
            log, session = db.get(QAAccessLog, rid), db.get(ChatSession, sid)
            assert log and log.session_id == sid and session.status == 'deleted'
            owner, age = log.user_id, max(0, int((datetime.now(timezone.utc).replace(tzinfo=None) - log.created_at).total_seconds() * 1000))
        result = service.finalize(service.session_factory, get_history_store(), owner, sid, rid,
                                  status='cancelled', reason='qa_interrupted_cleanup', elapsed_ms=age,
                                  write_history=False)
        assert result['status'] == 'cancelled'
        report['closed'].append({'request_id': rid, 'session_id': sid, 'result': result,
                                 'manually_reconciled_qa': True})
    with service.session_factory() as db:
        report['processing_remaining'] = len(list(db.scalars(select(QAAccessLog.id).where(QAAccessLog.status == 'processing'))))
    report['passed'] = report['processing_remaining'] == 0
    (ROOT / 'docs/evidence/stage5/interrupted-qa-cleanup.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert report['passed']
    print(json.dumps({'passed': True, 'exact_qa_requests_closed': len(report['closed'])}))


if __name__ == '__main__':
    main()
