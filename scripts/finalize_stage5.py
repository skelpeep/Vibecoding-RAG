"""Clean exact recorded QA resources and retain one labelled, real indexed demo."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business.database import get_engine
from atguigu.business.models import ChatSession, Department, KnowledgeUnit, Role, User
from scripts.verify_stage5_http import parse_sse


def main():
    out = ROOT / 'docs/evidence/stage5'
    fixture = json.loads((out / 'fixtures.json').read_text(encoding='utf-8'))
    credentials = json.loads((ROOT / 'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    recorded = set()
    # Never infer ownership from a title, creation date or broad username filter.
    for path in [*out.glob('http*.json'), out / 'stream-controls.json', out / 'leases.json']:
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            recorded.update(data.get('sessions', []))
            if data.get('session_id'):
                recorded.add(data['session_id'])
    visual = json.loads((out / 'ui/visual-fixtures.json').read_text(encoding='utf-8'))
    recorded.update(row['id'] for row in visual['sessions'].values())
    for path in [out / 'ui/interactions.json', out / 'ui/states.json']:
        data = json.loads(path.read_text(encoding='utf-8'))
        sessions = data.get('sessions', [])
        if isinstance(sessions, list):
            recorded.update(row['id'] if isinstance(row, dict) else row for row in sessions)
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': False,
              'removed_sessions': [], 'recorded_already_closed': [], 'demo': {}}
    with httpx.Client(base_url='http://127.0.0.1:8104', timeout=90, trust_env=False) as client:
        heads = {}
        with Session(get_engine()) as db:
            usernames = {u.id: u.username for u in db.scalars(select(User))}
            owned = {sid: db.get(ChatSession, sid).owner_id for sid in recorded if db.get(ChatSession, sid)}
        for name in ['kb_admin', 'alice', 'bob', 'carol', 'admin']:
            response = client.post('/api/auth/login', json={'username': name, 'password': credentials[name]})
            response.raise_for_status()
            heads[name] = {'Authorization': 'Bearer ' + response.json()['access_token']}
        for sid, owner in owned.items():
            name = usernames[owner]
            assert name in heads
            response = client.delete('/api/ai/chat/sessions/' + sid, headers=heads[name])
            assert response.status_code in [204, 404], response.status_code
            report['removed_sessions' if response.status_code == 204 else 'recorded_already_closed'].append(sid)
        public, private = fixture['unit_ids']
        response = client.request('DELETE', '/api/knowledge/units', headers=heads['kb_admin'], json={'unit_ids': [private]})
        response.raise_for_status()
        report['deleted_private_qa_unit'] = private
        response = client.put('/api/knowledge/units/' + public, headers=heads['kb_admin'], json={
            'title': '项目资料归档流程（示例）', 'category': '工作流程（示例）', 'tags': ['示例', '资料归档'],
            'summary': '明确归档申请时间、复核责任人和提交资料。',
            'content': '# 项目资料归档流程（示例）\n\n项目资料归档须在项目结束前三个工作日提交申请。\n\n申请人整理项目说明、交付清单和处理记录，交给资料管理员复核。资料管理员检查文件是否完整、责任人是否明确；复核通过后，由知识管理员发布。\n\n本资料用于演示知识问答，实际工作以组织正式发布的制度为准。'
        })
        response.raise_for_status()
        version = response.json()['latest_version']['id']
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            response = client.get('/api/knowledge/units/' + public, headers=heads['kb_admin'])
            response.raise_for_status()
            status = response.json()['latest_version']['status']
            if status == 'ready':
                break
            assert status != 'failed', 'Demo real indexing failed'
            time.sleep(2)
        else:
            raise TimeoutError('Demo worker did not finish')
        response = client.post(f'/api/knowledge/units/{public}/versions/{version}/activate', headers=heads['kb_admin'])
        response.raise_for_status()
        session = client.post('/api/ai/chat/sessions', headers=heads['kb_admin'], json={'title': '资料归档问答（示例）'})
        session.raise_for_status()
        sid = session.json()['id']
        with client.stream('POST', '/api/ai/chat/stream', headers=heads['kb_admin'],
                           json={'session_id': sid, 'question': '项目资料归档应该什么时候提交、由谁复核？'}) as response:
            assert response.status_code == 200
            events = list(parse_sse(response.iter_lines()))
        assert events[-1]['data']['status'] == 'completed', events[-1]
        source_event = [e for e in events if e['event'] == 'sources'][-1]
        assert {s['unit_id'] for s in source_event['data']['sources']} == {public}
        answer = ''.join(e['data']['text'] for e in events if e['event'] == 'delta')
        assert '资料管理员' in answer and ('三' in answer or '3' in answer)
        report['demo'] = {'unit_id': public, 'version_id': version, 'session_id': sid,
                          'owner': 'kb_admin', 'title': '项目资料归档流程（示例）',
                          'status': 'published', 'granted_users': ['kb_admin', 'alice', 'bob'],
                          'answer': answer, 'request_id': events[0]['data']['request_id']}
        with Session(get_engine()) as db:
            assert all(db.get(ChatSession, sid).status == 'deleted' for sid in owned)
            assert db.get(KnowledgeUnit, private).status == 'deleted'
            report['final_counts'] = {name: db.scalar(select(func.count()).select_from(model))
                for name, model in [('users', User), ('roles', Role), ('departments', Department)]}
            report['final_counts']['nondeleted_knowledge'] = db.scalar(select(func.count()).select_from(KnowledgeUnit).where(KnowledgeUnit.status != 'deleted'))
            assert db.scalar(select(User).where(User.username == 'abc123')) is not None
        report['passed'] = True
    (out / 'final-state.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'removed_sessions': len(report['removed_sessions']),
                      'demo_unit': report['demo']['unit_id'], 'counts': report['final_counts']}))


if __name__ == '__main__':
    main()
