"""Final ready/production/history/no-match checks using actual application services."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.verify_stage5_http import parse_sse


def main():
    out = ROOT / 'docs/evidence/stage5'
    credentials = json.loads((ROOT / 'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    fixtures = json.loads((out / 'fixtures.json').read_text(encoding='utf-8'))
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(), 'checks': [], 'passed': False}
    with httpx.Client(base_url='http://127.0.0.1:8104', timeout=90, trust_env=False) as client:
        assert client.get('/ready').json()['database_revision'] == '0004'
        login = client.post('/api/auth/login', json={'username': 'carol', 'password': credentials['carol']})
        login.raise_for_status()
        headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
        with client.stream('POST', '/api/ai/chat/stream', headers=headers,
                           json={'question': fixtures['no_match_question']}) as response:
            assert response.status_code == 200
            events = list(parse_sse(response.iter_lines()))
        report['no_match_events'] = events
        sid = events[0]['data']['session_id']
        try:
            assert events[-1]['event'] == 'end' and events[-1]['data']['status'] == 'no_match'
            assert not any(e['event'] == 'permission' for e in events)
            assert not any(e['event'] == 'sources' and e['data'].get('sources') for e in events)
            report['checks'].append('real completely unmatched reader question returns no_match without permission hint')
        finally:
            assert client.delete('/api/ai/chat/sessions/' + sid, headers=headers).status_code == 204
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:4175/chat', wait_until='networkidle')
        expect(page).to_have_url(__import__('re').compile(r'/login'))
        report['checks'].append('production deep-link requires login')
        page.get_by_label('用户名').fill('kb_admin')
        page.get_by_label('密码', exact=True).fill(credentials['kb_admin'])
        page.get_by_role('button', name='登录', exact=True).click()
        expect(page.get_by_role('heading', name='AI 问答', exact=True)).to_be_visible(timeout=20000)
        expect(page.locator('.chat-list-count')).to_be_visible()
        report['checks'].append('production build real login chat route and owned history list')
        if page.locator('.chat-session-select').count():
            page.locator('.chat-session-select').first.click()
            expect(page.locator('.chat-history-skeleton')).to_have_count(0, timeout=20000)
        expect(page.locator('.chat-markdown')).to_contain_text('资料管理员', timeout=20000)
        page.locator('.chat-source-button').first.click()
        expect(page.get_by_role('dialog')).to_contain_text('项目资料归档流程（示例）', timeout=20000)
        page.get_by_role('button', name='关闭来源', exact=True).click()
        report['checks'].append('production retained demo answer and freshly authorized citation readable')
        page.screenshot(path=str(out / 'production-chat.png'), full_page=True)
        assert not errors
        report['page_errors'] = errors
        browser.close()
    report['passed'] = True
    (out / 'production-smoke.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'checks': len(report['checks'])}))


if __name__ == '__main__':
    main()
