"""Real stage-five UI/model checks; uses only recorded fixtures and own sessions."""
import json
import os
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/stage5/ui'
WEB = os.getenv('STAGE5_WEB_ORIGIN', 'http://127.0.0.1:5185')
API = os.getenv('STAGE5_API_ORIGIN', 'http://127.0.0.1:8104')

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    credentials = json.loads((ROOT / 'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    fixture = json.loads((ROOT / 'docs/evidence/stage5/fixtures.json').read_text(encoding='utf-8'))
    report = {'run': uuid4().hex[:10], 'checks': [], 'screens': [], 'errors': [], 'sessions': [], 'kind': 'real_api_model'}
    cleanup = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        def login(username):
            context = browser.new_context(viewport={'width':1440, 'height':900})
            response = context.request.post(API + '/api/auth/login', data={'username': username, 'password': credentials[username]})
            assert response.ok, response.status
            headers = {'Authorization':'Bearer ' + response.json()['access_token']}
            context.add_init_script('sessionStorage.setItem("kb-platform-token", ' + json.dumps(response.json()['access_token']) + ')')
            page = context.new_page()
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
            page.goto(WEB + '/chat', wait_until='networkidle')
            expect(page.get_by_role('heading', name='AI 问答', exact=True)).to_be_visible()
            return context, page, headers
        def check(name):
            report['checks'].append(name)
        def capture(page, name, detail=True):
            for width in (1440,768,390):
                page.set_viewport_size({'width':width, 'height':900})
                if width < 1100 and detail and not page.locator('.chat-detail-open').count():
                    page.locator('.chat-session-select').first.click()
                page.evaluate('document.fonts.ready')
                expect(page.locator('.chat-history-skeleton')).to_have_count(0,timeout=20000)
                page.evaluate('Promise.all(document.getAnimations().map(animation=>animation.finished.catch(()=>{})))')
                page.screenshot(path=str(OUT / f'{name}-{width}.png'), full_page=True)
                overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
                report['screens'].append({'name':name, 'width':width, 'overflow':overflow})
                assert not overflow, (name,width)
            page.set_viewport_size({'width':1440,'height':900})
        def create(page,context,headers):
            with page.expect_response('**/api/ai/chat/sessions') as response:
                page.get_by_role('button', name='新建会话', exact=True).click()
            result=response.value.json()
            report['sessions'].append(result['id']);cleanup.append((context,headers,result['id']))
            expect(page.get_by_role('textbox', name='继续提问', exact=True)).to_be_visible()
            return result['id']
        def ask(page,text):
            page.locator('#chat-question').fill(text)
            page.get_by_role('button', name='发送问题', exact=True).click()
            expect(page.get_by_role('button', name='停止生成', exact=True)).to_be_visible(timeout=20000)
            expect(page.get_by_role('button', name='发送问题', exact=True)).to_be_visible(timeout=240000)
            expect(page.locator('.chat-turn').last.locator('.chat-turn-status')).not_to_have_text('生成中', timeout=20000)
        try:
            alice,page,headers=login('alice')
            sid=create(page,alice,headers)
            capture(page,'empty')
            check('真实创建本人会话及三宽度空态')
            field=page.locator('#chat-question')
            field.fill('第一行');field.press('Shift+Enter');field.type('第二行')
            assert '\n' in field.input_value()
            page.evaluate("document.querySelector('#chat-question').dispatchEvent(new CompositionEvent('compositionstart', {bubbles:true}))")
            field.press('Enter');assert page.locator('.chat-turn').count()==0
            page.evaluate("document.querySelector('#chat-question').dispatchEvent(new CompositionEvent('compositionend', {bubbles:true}))")
            check('中文组合输入不误发送，Shift Enter换行')
            ask(page,fixture['question'])
            expect(page.locator('.chat-turn').last.locator('.chat-turn-status')).to_have_text('已完成', timeout=20000)
            assert page.locator('.chat-source-button').count()>=2
            expect(page.locator('.chat-answer').last).to_contain_text(fixture['restricted_marker'])
            capture(page,'all-authorized')
            check('无商品名称真实模型生成，两份有权知识引用')
            page.locator('.chat-source-button').first.click()
            expect(page.locator('.chat-citation-detail')).to_be_visible(timeout=20000)
            assert not page.locator('a[href^="/knowledge"]').count()
            capture(page,'citation')
            page.get_by_role('button', name='关闭来源', exact=True).click()
            check('普通提问者无知识维护菜单仍可读取鉴权引用')
            page.reload(wait_until='networkidle');page.locator('.chat-session-select').first.click()
            expect(page.locator('.chat-source-button').first).to_be_visible(timeout=20000)
            check('刷新后会话和回答真实持久化')
            ask(page,'请只重复前面提到的内部校验编号。')
            expect(page.locator('.chat-turn').last.locator('.chat-answer')).to_contain_text(fixture['restricted_marker'],timeout=20000)
            check('同会话真实多轮追问')
            empty_sid=create(page,alice,headers)
            ask(page,fixture['no_match_question'])
            expect(page.locator('.chat-turn').last.locator('.chat-turn-status')).to_have_text(__import__('re').compile('未找到依据|依据不足'), timeout=20000)
            report['no_match_actual_status']=page.locator('.chat-turn').last.locator('.chat-turn-status').inner_text()
            assert page.locator('.chat-source-button').count()==0
            capture(page,'no-match')
            check('真实无依据问题安全拒答及无引用提示，实际终态记录')
            page.set_viewport_size({'width':390,'height':900})
            page.get_by_role('button', name='返回历史会话', exact=True).click()
            expect(page.locator('.chat-sessions')).to_be_visible()
            expect(page.locator('.chat-conversation')).not_to_be_visible()
            page.locator('.chat-session-select').first.click()
            expect(page.locator('.chat-conversation')).to_be_visible()
            expect(page.locator('.chat-sessions')).not_to_be_visible()
            check('手机历史列表与详情单区域切换和返回')
            page.set_viewport_size({'width':1440,'height':900})
            stop_sid=create(page,alice,headers)
            page.locator('#chat-question').fill(fixture['question'])
            with page.expect_response('**/api/ai/chat/stream'):
                page.get_by_role('button', name='发送问题', exact=True).click()
            expect(page.get_by_role('button',name='停止生成',exact=True)).to_be_visible()
            page.get_by_role('button',name='停止生成',exact=True).click()
            expect(page.locator('.chat-turn-status').last).to_have_text('已停止')
            expect(page.locator('.chat-source-button')).to_have_count(0)
            capture(page,'stopped')
            history=alice.request.get(API+'/api/ai/chat/sessions/'+stop_sid+'/messages',headers=headers)
            assert history.ok
            check('真实流式停止并清空回答引用')
            bob,bobpage,bobheaders=login('bob')
            create(bobpage,bob,bobheaders);ask(bobpage,fixture['question'])
            expect(bobpage.locator('.chat-turn-status').last).to_have_text('已完成',timeout=20000)
            assert bobpage.locator('.chat-source-button').count()==1
            assert fixture['restricted_marker'] not in bobpage.locator('.chat-conversation').inner_text()
            capture(bobpage,'partial-authorized')
            check('真实部分有权回答只展示一份有权来源')
            carol,carolpage,carolheaders=login('carol')
            create(carolpage,carol,carolheaders);ask(carolpage,fixture['question'])
            expect(carolpage.locator('.chat-turn-status').last).to_have_text('访问范围不足',timeout=20000)
            assert not carolpage.locator('.chat-source-button').count()
            assert fixture['restricted_marker'] not in carolpage.locator('.chat-conversation').inner_text()
            capture(carolpage,'restricted')
            check('真实全部无权提示，无标题正文引用泄露')
            page.locator('.chat-session-list li').filter(has_text='新会话').first.get_by_role('button',name='删除会话：新会话').click()
            page.get_by_role('button',name='删除会话',exact=True).click()
            expect(page.get_by_role('dialog')).not_to_be_visible()
            check('真实会话删除确认')
            assert not report['errors'],report['errors']
        finally:
            for context,headers,sid in cleanup:
                result=context.request.delete(API+'/api/ai/chat/sessions/'+sid,headers=headers)
                assert result.status in (204,404),result.status
            report['cleanup']='exact own session ids deleted'
            (OUT/'interactions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()
    print(json.dumps({'checks':len(report['checks']),'screens':len(report['screens']),'errors':report['errors']},ensure_ascii=False))

if __name__=='__main__':main()
