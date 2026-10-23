"""Real no-match -> UI draft -> current published version -> model verified close."""
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_stage5_http import parse_sse
OUT=ROOT/'docs/evidence/stage6/ui'
WEB='http://127.0.0.1:5186'
API='http://127.0.0.1:8105'


def main():
    run=uuid4().hex[:8];question=f'苍鹭{run}轨道微藻的休眠保存时长是多少？'
    report={'run':run,'question':question,'passed':False,'checks':[],'errors':[]}
    def save():(OUT/'gap-draft.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    def check(name):report['checks'].append(name);save();print('PASS '+name,flush=True)
    creds=json.loads((ROOT/'var/setup/stage2-accounts.json').read_text(encoding='utf8'))
    with httpx.Client(base_url=API,trust_env=False,timeout=300) as c:
        r=c.post('/api/auth/login',json={'username':'kb_admin','password':creds['kb_admin']});r.raise_for_status()
        token=r.json()['access_token'];h={'Authorization':'Bearer '+token}
        events=list(parse_sse(c.post('/api/ai/chat/stream',headers=h,json={'question':question}).text.splitlines()))
        assert events[-1]['data']['status'] in {'no_match','low_confidence'},events[-1]
        mined=c.post('/api/settlement/mine',headers=h);mined.raise_for_status()
        gap=next(g for g in c.get('/api/settlement/knowledge-gaps?page_size=100',headers=h).json()['items'] if g['question_pattern']==question)
        report['gap_id']=gap['id'];check('actual model no-match creates mineable knowledge gap')
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context(viewport={'width':390,'height':900})
            context.add_init_script('sessionStorage.setItem("kb-platform-token",'+json.dumps(token)+')')
            page=context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
            try:
                page.goto(WEB+'/settlement?tab=gaps',wait_until='networkidle')
                row=page.locator('.settlement-row').filter(has=page.get_by_role('heading',name=question,exact=True))
                row.get_by_role('link',name='创建知识草稿').click()
                expect(page.get_by_label('标题',exact=False)).to_have_value(question)
                page.get_by_label('正文',exact=False).fill(f'# 苍鹭{run}轨道微藻休眠保存规范\n\n苍鹭{run}轨道微藻的休眠保存时长为七十二小时，也就是 72 小时。保存期间每十二小时检查一次容器封口，完成记录后由实验负责人签名。本规范为交付演示专用虚构资料。')
                page.get_by_label('全局开放',exact=False).check()
                with page.expect_response('**/api/settlement/knowledge-gaps/*/draft') as response:
                    page.get_by_role('button',name='保存知识',exact=True).click()
                result=response.value.json();assert response.value.status==201,result
                uid=result['unit']['id'];report['unit_id']=uid;save()
                assert result['gap']['status']=='unresolved'
                expect(page.get_by_role('heading',name='知识详情',exact=True)).to_be_visible()
                page.screenshot(path=str(OUT/'gap-created-draft-390.png'),full_page=True)
                check('mobile UI prefilled title, real draft creation, persisted linkage remains unresolved')
                deadline=time.monotonic()+180
                while time.monotonic()<deadline:
                    detail=c.get('/api/knowledge/units/'+uid,headers=h).json()
                    if detail['latest_version']['status']=='ready':break
                    assert detail['latest_version']['status']!='failed';time.sleep(2)
                else:raise TimeoutError('Draft indexing did not finish')
                page.get_by_role('button',name='版本历史',exact=True).click()
                page.get_by_role('button',name='激活',exact=True).click()
                page.get_by_role('button',name='确认激活',exact=True).click()
                expect(page.locator('.el-message-box')).not_to_be_visible()
                page.get_by_role('button',name='正文',exact=True).click()
                page.get_by_role('button',name='发布知识',exact=True).click()
                page.locator('.el-message-box').get_by_role('button',name='发布知识',exact=True).click()
                expect(page.get_by_role('button',name='撤销发布',exact=True)).to_be_visible()
                check('real worker indexing followed by mobile version activation and publication')
                page.goto(WEB+'/settlement?tab=gaps',wait_until='networkidle')
                row=page.locator('.settlement-row').filter(has=page.get_by_role('heading',name=question,exact=True))
                row.get_by_role('link',name='验证原问题',exact=True).click()
                expect(page.locator('#chat-question')).to_have_value(question)
                page.get_by_role('button',name='发送问题',exact=True).click()
                expect(page.locator('.chat-turn-status').last).to_have_text('已完成',timeout=240000)
                expect(page.locator('.chat-answer').last).to_contain_text('72')
                page.get_by_role('button',name='用此回答确认补全',exact=True).click()
                expect(page.get_by_role('heading',name='知识沉淀',exact=True)).to_be_visible(timeout=20000)
                expect(page.get_by_label('状态',exact=True)).to_have_value('resolved')
                expect(page.locator('.settlement-row').filter(has=page.get_by_role('heading',name=question,exact=True))).to_have_count(1)
                page.screenshot(path=str(OUT/'gap-ui-resolved-390.png'),full_page=True)
                check('mobile original-question generation and one-click server-verified resolution')
                report['passed']=not report['errors'];assert report['passed']
            finally:
                save();browser.close()


if __name__=='__main__':main()
