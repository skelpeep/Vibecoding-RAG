"""Additional real UI transitions; network-only states are labelled separately."""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/stage4/ui'
API='http://127.0.0.1:8103'
WEB='http://127.0.0.1:5184'

def main():
    base=json.loads((OUT/'report.json').read_text(encoding='utf-8'))
    unit_id=base['unit_ids'][0]
    credentials=json.loads((ROOT/'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    report={'checks':[],'injected_state_checks':[],'errors':[],'unit_id':unit_id}
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':900})
        page.on('pageerror',lambda e:report['errors'].append(str(e)))
        api=page.request
        token=api.post(API+'/api/auth/login',data={'username':'kb_admin','password':credentials['kb_admin']}).json()['access_token']
        headers={'Authorization':'Bearer '+token}
        page.add_init_script('sessionStorage.setItem("kb-platform-token",'+json.dumps(token)+')')
        try:
            page.goto(WEB+'/knowledge/'+unit_id,wait_until='networkidle')
            page.get_by_role('button',name='版本历史',exact=True).click()
            row=page.locator('.version-list li').first
            expect(row).to_contain_text('已就绪',timeout=30000)
            row.get_by_role('button',name='激活',exact=True).click()
            page.get_by_role('button',name='确认激活',exact=True).click()
            expect(row).to_contain_text('当前版本')
            page.get_by_role('button',name='正文',exact=True).click()
            page.get_by_role('button',name='发布知识',exact=True).click()
            page.get_by_role('button',name='发布知识',exact=True).last.click()
            expect(page.locator('.knowledge-object-heading')).to_contain_text('已发布')
            report['checks'].append('真实ready版本激活与发布')
            page.get_by_role('button',name='访问范围',exact=True).click()
            options=api.get(API+'/api/knowledge/permission-options',headers=headers).json()
            alice=next(x for x in options['users'] if x['username']=='alice')
            page.get_by_label('预览成员',exact=True).select_option(alice['id'])
            page.get_by_role('button',name='检查当前授权',exact=True).click()
            expect(page.locator('.preview-result')).to_contain_text('当前允许阅读')
            page.get_by_role('checkbox',name='全局开放').uncheck()
            page.get_by_role('checkbox',name='技术部',exact=True).check()
            page.locator('.grant-group').filter(has=page.locator('summary strong',has_text='角色')).locator('summary').click()
            page.locator('.grant-group').filter(has=page.locator('summary strong',has_text='个人')).locator('summary').click()
            page.locator('.grant-choices').get_by_role('checkbox').filter(visible=True).all()
            role_group=page.locator('.grant-group').filter(has=page.locator('summary strong',has_text='角色'))
            role_group.get_by_role('checkbox').first.check()
            user_group=page.locator('.grant-group').filter(has=page.locator('summary strong',has_text='个人'))
            user_group.get_by_role('checkbox').first.check()
            page.get_by_role('button',name='保存访问范围',exact=True).click()
            expect(page.get_by_role('button',name='保存访问范围',exact=True)).to_be_disabled()
            grants=api.get(API+f'/api/knowledge/units/{unit_id}/permissions',headers=headers).json()['grants']
            assert {x['target_type'] for x in grants}=={'department','role','user'}
            report['checks'].append('四维混合选择保存与发布后授权预览')
            page.get_by_role('checkbox',name='全局开放').check()
            page.get_by_role('button',name='保存访问范围',exact=True).click()
            expect(page.get_by_role('button',name='保存访问范围',exact=True)).to_be_disabled()
            page.get_by_role('button',name='正文',exact=True).click()
            page.get_by_role('button',name='撤销发布',exact=True).click()
            page.get_by_role('button',name='撤销发布',exact=True).last.click()
            expect(page.locator('.knowledge-object-heading')).to_contain_text('草稿')
            page.get_by_role('button',name='停用知识',exact=True).click()
            page.get_by_role('button',name='停用知识',exact=True).last.click()
            expect(page.locator('.knowledge-object-heading')).to_contain_text('已停用')
            page.get_by_role('button',name='恢复为草稿',exact=True).click()
            page.get_by_role('button',name='撤销发布',exact=True).click()
            expect(page.locator('.knowledge-object-heading')).to_contain_text('草稿')
            report['checks'].append('真实撤销发布、停用和恢复草稿')
            page.get_by_role('button',name='版本历史',exact=True).click()
            row=page.locator('.version-list li').first
            with page.expect_response('**/rebuild') as rebuilt:
                row.get_by_role('button',name='重建',exact=True).click()
            assert rebuilt.value.status==202
            expect(page.locator('.version-list li')).to_have_count(3)
            assert api.get(API+f'/api/knowledge/units/{unit_id}',headers=headers).json()['active_version']['version_number']==2
            report['checks'].append('真实重建新增版本，原激活版保持')
            # Current document request becomes inaccessible; clear the already-rendered content.
            detail_path='**/api/knowledge/units/'+unit_id
            page.route(detail_path,lambda route:route.fulfill(status=404,json={'detail':'资源不存在或不可访问'}))
            page.get_by_role('button',name='刷新知识详情',exact=True).click()
            expect(page.locator('.error-state')).to_be_visible()
            expect(page.locator('.document-title')).to_have_count(0)
            expect(page.locator('.version-content')).to_have_count(0)
            page.unroute(detail_path)
            report['injected_state_checks'].append('404权限响应后清除旧正文与版本')
            page.get_by_role('button',name='重新加载',exact=True).click()
            expect(page.locator('.document-title')).to_be_visible()
            report['checks'].append('详情失败后真实请求恢复')
            page.goto(WEB+'/knowledge/import',wait_until='networkidle')
            folder=ROOT/'var/stage4-ui-directory'
            (folder/'sub').mkdir(parents=True,exist_ok=True)
            (folder/'root.txt').write_text('根目录知识',encoding='utf-8')
            (folder/'sub/child.md').write_text('# 子目录知识',encoding='utf-8')
            page.get_by_label('选择导入目录',exact=True).set_input_files(str(folder))
            expect(page.locator('.selected-files li')).to_have_count(2)
            expect(page.locator('.selected-files')).to_contain_text('sub/child.md')
            page.get_by_role('button',name='清空',exact=True).click()
            data=page.evaluate_handle("""()=>{const d=new DataTransfer();d.items.add(new File(['拖拽正文'],'drop.txt',{type:'text/plain'}));return d}""")
            page.locator('.upload-zone').dispatch_event('drop',{'dataTransfer':data})
            expect(page.locator('.selected-files li')).to_have_count(1)
            page.get_by_role('button',name='移除 drop.txt',exact=True).click()
            report['checks'].append('浏览器目录递归路径与拖拽文件、移除选择')
            page.set_viewport_size({'width':390,'height':900})
            expect(page.get_by_label('导入批次',exact=True)).to_be_visible()
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            page.screenshot(path=str(OUT/'import-final-390.png'),full_page=True)
            report['checks'].append('手机批次选择优先展示文件任务，无整页横溢')
            page.goto(WEB+'/knowledge',wait_until='networkidle')
            page.get_by_label('搜索知识',exact=True).fill('不存在_'+base['prefix'])
            expect(page.get_by_text('当前范围内没有知识')).to_be_visible()
            report['checks'].append('真实搜索空结果')
            assert not report['errors'],report['errors']
        finally:
            (OUT/'states.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':main()
