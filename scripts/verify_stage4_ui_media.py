"""Real authorized media display and retry button. The retry cause is test-injected."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/stage4/ui'
API='http://127.0.0.1:8103'
WEB='http://127.0.0.1:5184'

def main():
    demo=json.loads((ROOT/'docs/evidence/stage4/demo.json').read_text(encoding='utf-8'))
    credentials=json.loads((ROOT/'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    report={'checks':[],'images':[],'page_errors':[],'retry_cause':'A timeout was injected through the real worker failure transition. Retry HTTP and UI use persisted state.'}
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':900})
        page.on('pageerror',lambda e:report['page_errors'].append(str(e)))
        token=page.request.post(API+'/api/auth/login',data={'username':'kb_admin','password':credentials['kb_admin']}).json()['access_token']
        page.add_init_script('sessionStorage.setItem("kb-platform-token",'+json.dumps(token)+')')
        page.add_init_script('window.revokedUrls=[];const revoke=URL.revokeObjectURL.bind(URL);URL.revokeObjectURL=function(url){window.revokedUrls.push(url);return revoke(url)}')
        image_requests=[]
        page.on('request',lambda r:image_requests.append({'url':r.url,'bearer':r.headers.get('authorization','').startswith('Bearer ')}) if r.url.endswith('/image') else None)
        try:
            page.goto(WEB+'/knowledge/'+demo['image_unit_id'],wait_until='networkidle')
            expect(page.locator('.knowledge-image img')).to_have_count(1)
            page.wait_for_function('document.querySelector(".knowledge-image img")?.naturalWidth>0')
            src=page.locator('.knowledge-image img').get_attribute('src')
            assert src.startswith('blob:')
            assert image_requests and all(r['bearer'] for r in image_requests)
            assert not any('token=' in r['url'] for r in image_requests)
            report['checks'].append('Real image endpoint requires Bearer and displayed source is a blob URL')
            for width in (1440,768,390):
                page.set_viewport_size({'width':width,'height':900})
                page.screenshot(path=str(OUT/f'image-{width}.png'),full_page=True)
                assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                report['images'].append({'width':width,'natural_width':page.locator('.knowledge-image img').evaluate('(el)=>el.naturalWidth')})
            page.get_by_role('button',name='附件',exact=False).first.click()
            expect(page.locator('.knowledge-image img')).to_have_count(1)
            assert page.evaluate('(url)=>window.revokedUrls.includes(url)',src)
            report['checks'].append('Image object URL revoked when leaving body tab; attachment tab shows authorized image')
            page.goto(WEB+'/knowledge/import?batch='+demo['retry_batch_id'],wait_until='networkidle')
            expect(page.locator('.task-list')).to_contain_text('等待自动重试')
            page.screenshot(path=str(OUT/'retry-before-390.png'),full_page=True)
            with page.expect_response('**/tasks/'+demo['retry_task_id']+'/retry') as response:
                page.get_by_role('button',name='重试',exact=True).click()
            assert response.value.status==200,response.value.text()
            task=response.value.json()
            assert task['id']==demo['retry_task_id'] and task['retry_at'] is None and task['attempts']==1
            report['retry_task']=task
            expect(page.locator('.task-list')).to_contain_text('等待处理')
            report['checks'].append('Retry button clears scheduled backoff using the same persisted task ID and preserves attempt count')
            page.screenshot(path=str(OUT/'retry-after-390.png'),full_page=True)
            assert not report['page_errors']
        finally:
            (OUT/'media-retry.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()
    print(json.dumps({'checks':report['checks'],'page_errors':report['page_errors']},ensure_ascii=False))

if __name__=='__main__':main()
