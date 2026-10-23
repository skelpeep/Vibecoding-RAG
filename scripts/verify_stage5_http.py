"""Real HTTP/MySQL/Mongo/Milvus/model stage-five acceptance on isolated fixtures.

No mock vectors or answers are used here. Mutation checks only change this run's
documents and sessions. Partial failure and midstream cancellation are explicit.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business.database import get_engine
from atguigu.business.models import QAAccessLog
from atguigu.business.seed import seed_id

BASE = os.getenv('STAGE5_API_BASE', 'http://127.0.0.1:8104')
OUT = ROOT / 'docs/evidence/stage5'


def parse_sse(lines):
    event, data = 'message', []
    for line in lines:
        if not line:
            if data:
                yield {'event': event, 'data': json.loads('\n'.join(data))}
            event, data = 'message', []
        elif line.startswith('event:'):
            event = line[6:].lstrip()
        elif line.startswith('data:'):
            data.append(line[5:].lstrip())
    if data:
        yield {'event': event, 'data': json.loads('\n'.join(data))}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fixtures = json.loads((OUT / 'fixtures.json').read_text(encoding='utf-8'))
    assert fixtures['ready']
    creds = json.loads((ROOT / 'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': False,
              'services': 'real HTTP/MySQL/MongoDB/MinIO/Milvus/chat/embedding/rerank',
              'fixture_run_id': fixtures['run_id'], 'checks': [], 'requests': [], 'sessions': [],
              'mutations_restored': False}
    uid, private_uid = fixtures['unit_ids']
    heads = {}
    client = httpx.Client(base_url=BASE, timeout=180, trust_env=False)

    def check(name, **details):
        report['checks'].append({'name': name, **details})
        save()
        print('PASS ' + name, flush=True)

    def save():
        (OUT / 'http.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def req(method, path, who='alice', expected=200, **kwargs):
        response = client.request(method, path, headers=heads[who], **kwargs)
        assert response.status_code == expected, f'{method} {path} HTTP {response.status_code}: {response.text[:160]}'
        return response

    def chat(who, question, session_id=None):
        payload = {'question': question}
        if session_id:
            payload['session_id'] = session_id
        start = time.monotonic()
        events = []
        with client.stream('POST', '/api/ai/chat/stream', headers=heads[who], json=payload) as response:
            assert response.status_code == 200, f'chat {who}: {response.status_code}'
            assert response.headers['content-type'].startswith('text/event-stream')
            for event in parse_sse(response.iter_lines()):
                events.append(event)
        assert events and events[0]['event'] == 'meta', events
        assert events[-1]['event'] == 'end', events
        meta, end = events[0]['data'], events[-1]['data']
        rid, sid = meta['request_id'], meta['session_id']
        if sid not in report['sessions']:
            report['sessions'].append(sid)
        seqs = [e['data']['seq'] for e in events]
        assert seqs == sorted(set(seqs)), seqs
        assert all(e['data']['request_id'] == rid and e['data']['session_id'] == sid for e in events)
        answer = ''.join(e['data'].get('text', '') for e in events if e['event'] == 'delta')
        source_events = [e for e in events if e['event'] == 'sources']
        sources = source_events[-1]['data'].get('sources', []) if source_events else []
        row = {'who': who, 'request_id': rid, 'session_id': sid, 'status': end['status'],
               'events': [e['event'] for e in events], 'elapsed_seconds': round(time.monotonic() - start, 3),
               'sources': sources, 'answer': answer, 'end': end}
        report['requests'].append(row)
        save()
        return row, events

    def grants(unit, names):
        req('POST', f'/api/knowledge/units/{unit}/permissions', who='kb_admin',
            json={'grants': [{'target_type': 'user', 'target_id': seed_id('user/' + n)} for n in names]})

    try:
        assert client.get('/ready').json()['database_revision'] == '0004'
        assert client.post('/api/ai/chat/stream', json={'question': '测试'}).status_code == 401
        for name in ['kb_admin', 'admin', 'alice', 'bob', 'carol']:
            response = client.post('/api/auth/login', json={'username': name, 'password': creds[name]})
            response.raise_for_status()
            heads[name] = {'Authorization': 'Bearer ' + response.json()['access_token']}
        check('ready 0004 and anonymous chat denied')
        req('POST', '/api/ai/chat/stream', expected=422,
            json={'question': fixtures['question'], 'user_id': seed_id('user/kb_admin')})
        check('client user_id forgery rejected before streaming')
        complete, _ = chat('alice', fixtures['question'])
        assert complete['status'] == 'completed', complete
        assert {s['unit_id'] for s in complete['sources']} == {uid, private_uid}, complete['sources']
        assert fixtures['restricted_marker'] in complete['answer'], complete['answer']
        assert '三' in complete['answer'] or '3' in complete['answer']
        with Session(get_engine()) as db:
            log = db.get(QAAccessLog, complete['request_id'])
            assert log.details_json['metrics']['dense_recalled_count'] > 0
            assert log.details_json['metrics']['invalid_vector_count'] == 0
        check('general question without product name; all grants retrieve both sources; real generated answer')
        partial, pe = chat('bob', fixtures['question'])
        assert partial['status'] == 'completed', partial
        assert {s['unit_id'] for s in partial['sources']} == {uid}
        raw = json.dumps(pe, ensure_ascii=False)
        assert fixtures['restricted_marker'] not in raw and private_uid not in raw
        assert any(e['event'] == 'permission' for e in pe)
        check('same question partial authorization; denied identifiers/title/body absent from SSE')
        for who in ['carol', 'admin']:
            denied, events = chat(who, fixtures['question'])
            assert denied['status'] == 'restricted', denied
            assert not denied['sources']
            assert fixtures['restricted_marker'] not in json.dumps(events, ensure_ascii=False)
        check('same question all denied; system administrator has no body bypass')
        missing, _ = chat('alice', fixtures['no_match_question'])
        assert missing['status'] in ['no_match', 'low_confidence'], missing
        assert not missing['sources']
        check('unrelated question has no factual fabricated answer')
        sid, rid = complete['session_id'], complete['request_id']
        req('GET', '/api/ai/chat/sessions/' + sid + '/messages', who='bob', expected=404)
        req('DELETE', '/api/ai/chat/sessions/' + sid, who='bob', expected=404)
        req('GET', '/api/ai/chat/requests/' + rid, who='bob', expected=404)
        req('POST', '/api/ai/chat/requests/' + rid + '/cancel', who='bob', expected=404)
        source = next(s for s in complete['sources'] if s['unit_id'] == private_uid)
        cite = '/api/ai/chat/requests/' + rid + '/citations/' + source['chunk_id']
        req('GET', cite, who='bob', expected=404)
        citation = req('GET', cite).json()
        assert fixtures['restricted_marker'] in json.dumps(citation, ensure_ascii=False)
        check('session/history/request/cancel/citation ownership; authorized live source traceability')
        follow, _ = chat('alice', '那应该什么时候提交？', sid)
        assert follow['session_id'] == sid and follow['status'] == 'completed', follow
        check('owned multiround rewrite resolves pronoun from authorized history')
        grants(private_uid, ['kb_admin'])
        req('GET', cite, expected=404)
        history = req('GET', '/api/ai/chat/sessions/' + sid + '/messages').json()
        first = next(r for r in history['items'] if r['request_id'] == rid)
        assert first['assistant']['redacted'] and first['user']['redacted'], first
        assert fixtures['restricted_marker'] not in json.dumps(history, ensure_ascii=False)
        revoked, re = chat('alice', '刚才的内部校验编号是什么？', sid)
        assert fixtures['restricted_marker'] not in json.dumps(re, ensure_ascii=False)
        assert not any(s['unit_id'] == private_uid for s in revoked['sources'])
        check('revocation immediately rejects old citation; entire sourced turn redacted from history and new generation')
        grants(private_uid, ['kb_admin', 'alice'])
        # Disconnect at meta during real retrieval; no mock delay or model response.
        with client.stream('POST', '/api/ai/chat/stream', headers=heads['alice'],
                           json={'question': fixtures['question']}) as response:
            assert response.status_code == 200
            meta = next(parse_sse(response.iter_lines()))['data']
        cancel_id = meta['request_id']
        report['sessions'].append(meta['session_id'])
        terminal = None
        for _ in range(40):
            terminal = req('GET', '/api/ai/chat/requests/' + cancel_id).json()
            if terminal['status'] != 'processing':
                break
            time.sleep(.25)
        assert terminal['status'] == 'cancelled', terminal
        check('real client disconnect produces persistent cancelled terminal outcome', request_id=cancel_id)
        # End-to-end logs are read directly; outward payloads never reveal denied IDs.
        ids = [r['request_id'] for r in report['requests']] + [cancel_id]
        with Session(get_engine()) as db:
            logs = list(db.scalars(select(QAAccessLog).where(QAAccessLog.id.in_(ids))))
            assert len(logs) == len(ids)
            assert all(r.status != 'processing' and r.response_time_ms is not None for r in logs)
            all_log = next(r for r in logs if r.id == rid)
            assert {uid, private_uid} <= set(all_log.authorized_unit_ids_json)
            partial_log = next(r for r in logs if r.id == partial['request_id'])
            assert private_uid in partial_log.unauthorized_unit_ids_json
            assert private_uid not in partial_log.authorized_unit_ids_json
            assert all(r.cache_status != 'hit' for r in logs)
            report['log_summary'] = [{'request_id': r.id, 'status': r.status,
                'prompt_tokens': r.prompt_tokens, 'completion_tokens': r.completion_tokens,
                'total_tokens': r.total_tokens, 'model_usage': r.model_usage_json,
                'duration_ms': r.response_time_ms, 'first_token_ms': r.first_token_ms,
                'metrics': r.details_json.get('metrics'), 'usage_completeness': r.details_json.get('usage_completeness'),
                'recalled': r.recalled_unit_ids_json, 'allowed': r.authorized_unit_ids_json,
                'denied': r.unauthorized_unit_ids_json, 'cited': r.cited_sources_json} for r in logs]
        check('MySQL logs record terminal outcomes actual/unknown usage source sets and timings; no pretend FAQ hit')
        report['passed'] = True
    finally:
        if 'kb_admin' in heads:
            grants(uid, ['kb_admin', 'alice', 'bob'])
            grants(private_uid, ['kb_admin', 'alice'])
            report['mutations_restored'] = True
        save()
        client.close()
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks'])}))


if __name__ == '__main__':
    main()
