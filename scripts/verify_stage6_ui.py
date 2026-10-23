"""Actual browser/API/model interactions; only network state tests are injected."""
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'docs/evidence/stage6/ui'
WEB='http://127.0.0.1:5186'
API='http://127.0.0.1:8105'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    creds=json.loads((ROOT/'var/setup/stage2-accounts.json').read_text(encoding='utf8'))
    fixture=json.loads((ROOT/'docs/evidence/stage6/http.json').read_text(encoding='utf8'))
    report={'checks':[],'screens':[],'errors':[],'passed':False,'real_api':True}
    def save():(OUT/'interactions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    def check(name):report['checks'].append(name);save();print('PASS '+name,flush=True)
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        def login(who):
            context=browser.new_context(viewport={'width':1440,'height':1000})
            result=context.request.post(API+'/api/auth/login',data={'username':who,'password':creds[who]})
            assert result.ok
            token=result.json()['access_token'];headers={'Authorization':'Bearer '+token}
            context.add_init_script('sessionStorage.setItem("kb-platform-token",'+json.dumps(token)+')')
            page=context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
            return context,page,headers
        def go(page,path):
            page.goto(WEB+path,wait_until='networkidle');expect(page.locator('.skeleton-list')).to_have_count(0)
        def capture(page,name):
            for width in (1440,768,390):
                page.set_viewport_size({'width':width,'height':900});page.evaluate('document.fonts.ready')
                page.screenshot(path=str(OUT/f'{name}-{width}.png'),full_page=True)
                overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
                assert not overflow,(name,width)
                report['screens'].append({'name':name,'width':width,'overflow':False})
            page.set_viewport_size({'width':1440,'height':1000})
        def ask(page,question):
            page.locator('#chat-question').fill(question);page.get_by_role('button',name='发送问题',exact=True).click()
            expect(page.get_by_role('button',name='发送问题',exact=True)).to_be_enabled(timeout=240000) if False else None
            expect(page.locator('.chat-turn').last.locator('.chat-turn-status')).to_have_text('已完成',timeout=240000)
        try:
            admin,ap,ah=login('admin');go(ap,'/dashboard')
            expect(ap.get_by_role('heading',name='数据看板',exact=True)).to_be_visible()
            capture(ap,'dashboard')
            ap.get_by_label('开始日期').fill('2020-01-01');ap.get_by_label('结束日期').fill('2020-01-02')
            ap.get_by_role('button',name='应用范围').click();expect(ap.locator('.lead-number')).to_have_text('0')
            capture(ap,'dashboard-zero');check('dashboard actual date filter and honest zero at three widths')
            ap.get_by_label('聚合方式').select_option('week');ap.get_by_role('button',name='应用范围').click()
            expect(ap.locator('.lead-number')).to_have_text('0');check('weekly aggregation uses same selected range')
            ap.route('**/api/dashboard/overview?*',lambda route:route.abort())
            ap.get_by_role('button',name='刷新',exact=True).click();expect(ap.get_by_role('alert')).to_be_visible()
            capture(ap,'dashboard-network-error');ap.unroute('**/api/dashboard/overview?*')
            ap.get_by_role('button',name='重新加载',exact=True).click();expect(ap.locator('.lead-number')).to_have_text('0')
            check('injected network failure clears values, retry recovers from real API')
            kb,page,headers=login('kb_admin');go(page,'/settlement?tab=published')
            current=page.locator('.settlement-row').filter(has=page.get_by_role('heading',name=fixture['question'],exact=True))
            expect(current).to_have_count(1);capture(page,'published')
            current.get_by_role('button',name='编辑并重新审核').click()
            expect(page.get_by_label('标准答案')).to_be_visible()
            original=page.get_by_label('标准答案').input_value()
            page.get_by_label('标准答案').fill(original+'\n\n请按来源核对交接记录。')
            page.get_by_role('button',name='保存为待审核',exact=True).click()
            expect(page.locator('.el-dialog')).not_to_be_visible()
            page.get_by_role('button',name='FAQ 推荐审核',exact=True).click()
            current=page.locator('.settlement-row').filter(has=page.get_by_role('heading',name=fixture['question'],exact=True))
            expect(current).to_have_count(1);capture(page,'recommendations')
            current.get_by_role('button',name='审核答案').click();capture(page,'review-dialog')
            page.get_by_role('button',name='审核通过并发布',exact=True).click()
            expect(page.locator('.el-dialog')).not_to_be_visible()
            page.get_by_role('button',name='已发布 FAQ',exact=True).click();expect(current).to_have_count(1)
            check('real UI edits published FAQ into pending, opens review and publishes with Redis warming')
            current.get_by_role('button',name='撤回发布').click();page.get_by_role('button',name='确认撤回',exact=True).click()
            expect(current).to_have_count(0)
            page.get_by_label('状态',exact=True).select_option('withdrawn');expect(current).to_have_count(1)
            current.get_by_role('button',name='编辑并重新审核').click();page.get_by_label('标准答案').fill(original)
            page.get_by_role('button',name='保存为待审核',exact=True).click();expect(page.locator('.el-dialog')).not_to_be_visible()
            page.get_by_label('状态',exact=True).select_option('pending_review');expect(current).to_have_count(1)
            current.get_by_role('button',name='审核答案').click();page.get_by_role('button',name='审核通过并发布',exact=True).click()
            expect(page.locator('.el-dialog')).not_to_be_visible();check('real UI withdrawal and republishing restore original reviewed answer')
            employee,ep,eh=login('alice');go(ep,'/chat')
            ep.locator('#chat-question').fill(fixture['question']);ep.get_by_role('button',name='发送问题',exact=True).click()
            expect(ep.locator('.chat-turn-status').last).to_have_text('FAQ 缓存回答',timeout=60000)
            expect(ep.locator('.chat-answer').last).to_contain_text(fixture['marker'])
            capture(ep,'cached-answer');check('real browser streams Redis FAQ answer with explicit cache label')
            go(ep,'/settlement');expect(ep.get_by_role('heading',name='访问受限',exact=True)).to_be_visible()
            check('ordinary user route guard denies settlement')
            go(page,'/settlement?tab=gaps');capture(page,'gaps')
            page.get_by_label('状态',exact=True).select_option('resolved')
            gap=page.locator('.settlement-row').filter(has_text='银桦'+fixture['run'])
            expect(gap).to_have_count(1);capture(page,'resolved-gaps')
            gap.get_by_role('button',name='重新打开').click();expect(gap).to_have_count(0)
            page.get_by_label('状态',exact=True).select_option('unresolved');expect(gap).to_have_count(1)
            gap.get_by_role('link',name='验证原问题',exact=True).click()
            expect(page.locator('#chat-question')).to_have_value('银桦'+fixture['run']+'月面标本的冷链封签温度是多少？')
            question=page.locator('#chat-question').input_value();ask(page,question)
            page.get_by_role('button',name='用此回答确认补全').click()
            expect(page.get_by_role('heading',name='知识沉淀',exact=True)).to_be_visible(timeout=30000)
            expect(page.get_by_label('状态',exact=True)).to_have_value('resolved');expect(gap).to_have_count(1)
            check('real gap reopen, prefilled original question, model answer, one-click verified resolution')
            # Check unfinished questions remain usable with ignore/reopen actions.
            page.get_by_label('状态',exact=True).select_option('unresolved')
            if page.locator('.settlement-row').count():
                row=page.locator('.settlement-row').first;name=row.locator('h2').inner_text()
                row.get_by_role('button',name='忽略',exact=True).click();page.get_by_label('状态',exact=True).select_option('ignored')
                row=page.locator('.settlement-row').filter(has=page.get_by_role('heading',name=name,exact=True))
                expect(row).to_have_count(1);row.get_by_role('button',name='重新打开').click()
                check('real gap ignore and reopen state transitions')
            report['passed']=not report['errors'];assert report['passed'],report['errors']
        finally:
            if not report['passed']:
                for idx,context in enumerate(browser.contexts):
                    for j,page in enumerate(context.pages):
                        page.screenshot(path=str(OUT/f'failure-{idx}-{j}.png'),full_page=True)
            save();browser.close()
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'screens':len(report['screens']),'errors':report['errors']},ensure_ascii=False))


if __name__=='__main__':main()
