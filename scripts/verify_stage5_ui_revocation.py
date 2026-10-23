"""Real shared-fixture revocation after root HTTP suite; restore exact original grants."""
import json
import os
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import expect,sync_playwright
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/stage5/ui'
API=os.getenv('STAGE5_API_ORIGIN','http://127.0.0.1:8104')
WEB=os.getenv('STAGE5_WEB_ORIGIN','http://127.0.0.1:5185')
def main():
    credentials=json.loads((ROOT/'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    fixture=json.loads((ROOT/'docs/evidence/stage5/fixtures.json').read_text(encoding='utf-8'))
    report={'checks':[],'errors':[],'kind':'real_api_model_permission_revocation','sessions':{},'grants_restored':False}
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':900});api=context.request
        def token(user):
            response=api.post(API+'/api/auth/login',data={'username':user,'password':credentials[user]});assert response.ok
            return response.json()['access_token']
        alice_token=token('alice');headers={'Authorization':'Bearer '+alice_token};manage={'Authorization':'Bearer '+token('kb_admin')}
        context.add_init_script('sessionStorage.setItem("kb-platform-token",'+json.dumps(alice_token)+')')
        page=context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
        private=fixture['unit_ids'][1];permissions='/api/knowledge/units/'+private+'/permissions'
        original=api.get(API+permissions,headers=manage);assert original.ok
        grants=original.json()['grants']
        run=uuid4().hex[:8];title='S5视觉验收_'+run
        session=api.post(API+'/api/ai/chat/sessions',headers=headers,data={'title':title});assert session.ok
        sid=session.json()['id'];report['sessions']['answer']={'id':sid,'title':title}
        empty=api.post(API+'/api/ai/chat/sessions',headers=headers,data={'title':'S5空会话_'+run});assert empty.ok
        report['sessions']['empty']={'id':empty.json()['id'],'title':empty.json()['title']}
        try:
            page.goto(WEB+'/chat',wait_until='networkidle');page.locator('.chat-session-select').filter(has_text=title).click()
            page.locator('#chat-question').fill(fixture['question']);page.get_by_role('button',name='发送问题',exact=True).click()
            expect(page.get_by_role('button',name='发送问题',exact=True)).to_be_visible(timeout=240000)
            expect(page.locator('.chat-source-button')).to_have_count(2,timeout=20000)
            history=api.get(API+'/api/ai/chat/sessions/'+sid+'/messages',headers=headers).json()
            request_id=history['items'][-1]['request_id'];report['request_id']=request_id
            source=next(s for s in history['items'][-1]['assistant']['sources'] if s['unit_id']==private)
            response=api.post(API+permissions,headers=manage,data={'grants':[]});assert response.ok,response.text()
            page.locator('.chat-source-button').filter(has_text=source['title']).click()
            expect(page.get_by_role('dialog')).to_contain_text('此来源已不可读取',timeout=20000)
            expect(page.locator('.chat-turn').last).to_contain_text('回答与引用不再显示',timeout=20000)
            assert fixture['restricted_marker'] not in page.locator('.chat-conversation').inner_text()
            expect(page.locator('.chat-source-button')).to_have_count(0)
            page.screenshot(path=str(OUT/'citation-revoked-1440.png'),full_page=True)
            report['checks'].append('真实撤权后引用重新鉴权拒绝，整轮问题回答来源及时清除')
            page.get_by_role('button',name='关闭来源',exact=True).click()
            page.reload(wait_until='networkidle');page.locator('.chat-session-select').filter(has_text=title).click()
            expect(page.locator('.chat-turn').last).to_contain_text('回答与引用不再显示',timeout=20000)
            assert fixture['restricted_marker'] not in page.locator('.chat-conversation').inner_text()
            report['checks'].append('撤权后刷新历史仍整轮脱敏')
        finally:
            response=api.post(API+permissions,headers=manage,data={'grants':[{'target_type':g['target_type'],'target_id':g.get('target_id')} for g in grants]})
            assert response.ok,response.text();report['grants_restored']=True
            page.reload(wait_until='networkidle');page.locator('.chat-session-select').filter(has_text=title).click()
            expect(page.locator('.chat-source-button')).to_have_count(2,timeout=20000)
            report['checks'].append('精确恢复原授权，历史来源重新可读取')
            (OUT/'visual-fixtures.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()
    print(json.dumps({'checks':len(report['checks']),'errors':report['errors'],'grants_restored':report['grants_restored']},ensure_ascii=False))
if __name__=='__main__':main()
