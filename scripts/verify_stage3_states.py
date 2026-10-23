"""Read-only UI states, rendered dialogs, and role-specific route checks."""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/stage3/states'
BASE = 'http://127.0.0.1:5183'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    credentials = json.loads((ROOT / 'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    checks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width':390,'height':900})
        response = page.request.post(BASE + '/api/auth/login', data={'username':'admin','password':credentials['admin']})
        assert response.status == 200
        token = response.json()['access_token']
        page.goto(BASE + '/login')
        page.evaluate('(token)=>sessionStorage.setItem("kb-platform-token",token)', token)

        def goto(path):
            page.goto(BASE + path, wait_until='networkidle')
            expect(page.locator('h1')).to_be_visible()

        def screenshot(name):
            page.evaluate('document.fonts.ready')
            page.screenshot(path=str(OUT / (name+'.png')), full_page=False)

        goto('/org/users')
        page.get_by_role('button',name='新增用户',exact=True).click()
        expect(page.get_by_role('dialog').get_by_label('用户名',exact=False)).to_be_visible()
        page.wait_for_function("!document.querySelector('[class*=dialog-fade-enter]')")
        screenshot('mobile-form-top')
        page.get_by_role('dialog').get_by_role('button',name='保存',exact=True).scroll_into_view_if_needed()
        screenshot('mobile-form-bottom')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).not_to_be_visible()
        checks.append('mobile form rendered after transition; full form scroll and Escape')
        for route,selector,name in [('/org/roles','.object-row','role'),('/org/departments','.department-row','department')]:
            goto(route)
            page.locator(selector).first.click()
            expect(page.locator('.detail-pane')).to_be_visible()
            expect(page.locator('.skeleton-list')).to_have_count(0)
            if name=='role':
                for group in page.locator('details').all():
                    if not group.get_attribute('open') is not None:
                        group.locator('summary').click()
                    expect(group.locator('input').first).to_be_visible()
                assert page.locator('details input').count() == 37
                # Return to compact default for the screenshot.
                for group in page.locator('details').all()[1:]: group.locator('summary').click()
            page.evaluate('scrollTo(0,0)')
            page.screenshot(path=str(OUT / f'mobile-{name}-detail.png'), full_page=True)
            checks.append(f'mobile {name} detail fully loaded' + ('; all five permission groups expand' if name=='role' else ''))
        page.set_viewport_size({'width':1440,'height':900})
        goto('/org/users')
        page.get_by_role('button',name='停用',exact=True).click()
        expect(page.locator('tbody tr')).to_have_count(1)
        expect(page.locator('tbody')).to_contain_text('disabled_demo')
        page.get_by_role('button',name='全部用户',exact=True).click()
        expect(page.locator('tbody tr')).to_have_count(7)
        page.get_by_label('筛选部门',exact=True).select_option(label='　技术部')
        expect(page.locator('tbody tr')).to_have_count(2)
        page.get_by_label('筛选部门',exact=True).select_option('')
        expect(page.locator('tbody tr')).to_have_count(7)
        expect(page.get_by_role('button',name='下一页',exact=True)).to_be_disabled()
        checks.append('status/department filters and totals reflect real rows; single-page bounds disabled')

        # A delayed real response exposes the loading state without manufacturing data.
        page.route('**/api/org/users?*', lambda route: route.continue_())
        cdp = page.context.new_cdp_session(page)
        cdp.send('Network.enable')
        cdp.send('Network.emulateNetworkConditions',{'offline':False,'latency':1500,'downloadThroughput':-1,'uploadThroughput':-1})
        page.get_by_role('button',name='刷新用户',exact=True).click()
        expect(page.locator('.skeleton-list')).to_be_visible()
        screenshot('loading-real-response')
        cdp.send('Network.emulateNetworkConditions',{'offline':False,'latency':0,'downloadThroughput':-1,'uploadThroughput':-1})
        expect(page.locator('tbody tr')).to_have_count(7)
        page.unroute('**/api/org/users?*')
        checks.append('loading placeholder with delayed real API response')

        goto('/profile')
        page.get_by_label('显示名称',exact=False).fill('未保存资料检查')
        page.evaluate("dispatchEvent(new Event('focus'))")
        page.wait_for_load_state('networkidle')
        expect(page.get_by_label('显示名称',exact=False)).to_have_value('未保存资料检查')
        checks.append('identity refresh preserves unsaved profile fields')
        page.route('**/api/auth/me',lambda route:route.abort())
        goto('/org/users')
        assert '/unavailable' in page.url
        screenshot('unavailable')
        page.unroute('**/api/auth/me')
        page.get_by_role('button',name='重新连接',exact=True).click()
        page.wait_for_url('**/org/users')
        expect(page.locator('tbody tr')).to_have_count(7)
        checks.append('auth-service failure state and reconnect to intended route')
        goto('/does-not-exist')
        expect(page.locator('h1')).to_have_text('页面不存在')
        screenshot('not-found')
        page.get_by_role('button',name='退出登录',exact=True).click()
        page.wait_for_url('**/login')
        assert page.evaluate('sessionStorage.getItem("kb-platform-token")') is None
        checks.append('not-found route and explicit logout clear identity')
        response = page.request.post(BASE+'/api/auth/login',data={'username':'kb_admin','password':credentials['kb_admin']})
        assert response.status==200
        page.evaluate('(token)=>sessionStorage.setItem("kb-platform-token",token)',response.json()['access_token'])
        goto('/knowledge')
        expect(page.get_by_role('link',name='知识维护',exact=True)).to_be_visible()
        expect(page.get_by_role('link',name='用户管理',exact=True)).to_have_count(0)
        expect(page.locator('h2')).to_have_text('此功能尚未开放')
        goto('/org/users')
        assert page.url.endswith('/forbidden')
        screenshot('forbidden')
        checks.append('knowledge-admin menu plus honest future-module and forbidden states')
        browser.close()
    (OUT.parent/'states.json').write_text(json.dumps({'checks':checks,'passed':len(checks)},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':len(checks),'checks':checks},ensure_ascii=False))


if __name__=='__main__': main()
