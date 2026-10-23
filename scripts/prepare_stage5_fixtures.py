"""Create isolated, labelled QA documents using real stage-four indexing services."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from atguigu.business.seed import seed_id


def main():
    out = ROOT / 'docs/evidence/stage5'
    out.mkdir(parents=True, exist_ok=True)
    creds = json.loads((ROOT / 'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    base = os.getenv('STAGE5_FIXTURE_API', 'http://127.0.0.1:8104')
    run = uuid4().hex[:10]
    report = {'run_id': run, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'unit_ids': [], 'version_ids': [], 'tasks': [], 'ready': False,
              'question': '项目资料归档需要提前多久、由谁复核，以及内部校验编号是什么？',
              'no_match_question': '火星上的紫色鲸鱼每周会举办几次音乐会？',
              'restricted_marker': 'S5-PRIVATE-' + run}
    with httpx.Client(base_url=base, timeout=90, trust_env=False) as client:
        login = client.post('/api/auth/login', json={'username': 'kb_admin', 'password': creds['kb_admin']})
        login.raise_for_status()
        headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
        people = lambda names: [{'target_type': 'user', 'target_id': seed_id('user/' + n)} for n in names]
        documents = [
            {'title': '项目资料归档流程（阶段五验收 ' + run + '）',
             'content': '# 项目资料归档流程（测试资料）\n\n项目资料归档须在项目结束前三个工作日提交申请。申请人整理项目说明、交付清单和处理记录，再交给资料管理员复核。资料管理员检查文件是否完整、责任人是否明确，复核通过后由知识管理员发布。此流程不包含内部校验编号，校验规则请查阅独立的内部规范。\n\n本条为隔离的阶段五验收资料，标识 ' + run,
             'grants': people(['kb_admin', 'alice', 'bob'])},
            {'title': '资料归档内部校验规范（阶段五受限验收 ' + run + '）',
             'content': '# 资料归档内部校验规范（测试资料）\n\n项目资料归档的内部复核负责人为红杉复核组。内部校验编号是 S5-PRIVATE-' + run + '。内部复核负责人核对编号并将确认记录交给资料管理员，资料管理员收到内部确认后完成项目资料归档复核。该校验编号仅在这份独立受限规范内提供，不能从公开资料归档流程推断。\n\n这是隔离的阶段五验收资料，标识 ' + run,
             'grants': people(['kb_admin', 'alice'])},
        ]
        try:
            for document in documents:
                response = client.post('/api/knowledge/units', headers=headers,
                                       json={**document, 'category': '阶段五隔离验收 ' + run, 'tags': ['验收资料']})
                response.raise_for_status()
                row = response.json()
                report['unit_ids'].append(row['id'])
                report['version_ids'].append(row['latest_version']['id'])
                report['tasks'].append(row['task_id'])
                (out / 'fixtures.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            deadline = time.monotonic() + 300
            for uid, vid in zip(report['unit_ids'], report['version_ids']):
                while time.monotonic() < deadline:
                    detail = client.get('/api/knowledge/units/' + uid, headers=headers)
                    detail.raise_for_status()
                    status = detail.json()['latest_version']['status']
                    if status == 'ready':
                        break
                    if status == 'failed':
                        raise RuntimeError('QA fixture indexing failed')
                    time.sleep(2)
                else:
                    raise TimeoutError('QA fixture worker did not finish')
                for route, body in [(f'/units/{uid}/versions/{vid}/activate', None),
                                    (f'/units/{uid}/status', {'status': 'published'})]:
                    response = client.post('/api/knowledge' + route, headers=headers, json=body)
                    response.raise_for_status()
            report['ready'] = True
        finally:
            (out / 'fixtures.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ready': report['ready'], 'run_id': run, 'units': len(report['unit_ids'])}))


if __name__ == '__main__':
    main()
