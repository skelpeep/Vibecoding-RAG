"""Stage-four browser smoke against the real API; created resource IDs are recorded."""
import json
import os
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/evidence/stage4/ui'
WEB = os.getenv('STAGE4_WEB_ORIGIN', 'http://127.0.0.1:5184')
API = os.getenv('STAGE4_API_ORIGIN', 'http://127.0.0.1:8103')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    credentials = json.loads((ROOT / 'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    name = 'UI验证_' + uuid4().hex[:8]
    report = {'checks': [], 'screens': [], 'errors': [], 'unit_ids': [], 'batch_ids': [], 'prefix': name}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.on('pageerror', lambda error: report['errors'].append(str(error)))
        api = page.request
        login = api.post(API + '/api/auth/login', data={'username': 'kb_admin', 'password': credentials['kb_admin']})
        assert login.ok, login.status
        token = login.json()['access_token']
        headers = {'Authorization': 'Bearer ' + token}
        page.add_init_script('sessionStorage.setItem("kb-platform-token", ' + json.dumps(token) + ')')

        def check(label):
            report['checks'].append(label)

        def capture(label):
            for width in (1440, 768, 390):
                page.set_viewport_size({'width': width, 'height': 900})
                page.evaluate('document.fonts.ready')
                page.screenshot(path=str(OUT / f'{label}-{width}.png'), full_page=True)
                overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
                report['screens'].append({'name': label, 'width': width, 'overflow': overflow})
                assert not overflow, (label, width)
            page.set_viewport_size({'width': 1440, 'height': 900})

        try:
            page.goto(WEB + '/knowledge', wait_until='networkidle')
            expect(page.get_by_role('heading', name='知识维护', exact=True)).to_be_visible()
            expect(page.locator('.error-state')).to_have_count(0)
            check('知识列表真实读取')
            page.get_by_role('link', name='新建知识', exact=True).click()
            page.get_by_label('标题', exact=False).fill(name + ' 服务交接说明')
            page.get_by_label('正文', exact=False).fill('# 服务交接说明\n\n交接前确认负责人、服务入口与故障联系渠道。\n\n值班人员记录处理过程，知识管理员在复核后发布新版本。')
            page.get_by_label('分类', exact=True).fill('工作流程')
            page.get_by_label('标签', exact=True).fill('交接，服务管理')
            page.get_by_label('摘要', exact=True).fill('说明服务交接的资料、责任人与发布步骤。')
            capture('editor')
            page.get_by_role('button', name='保存知识', exact=True).click()
            page.wait_for_url('**/knowledge/*', timeout=20000)
            expect(page.get_by_role('heading', name='知识详情', exact=True)).to_be_visible(timeout=20000)
            unit_id = page.url.rsplit('/', 1)[-1]
            report['unit_ids'].append(unit_id)
            detail = api.get(API + '/api/knowledge/units/' + unit_id, headers=headers)
            assert detail.ok
            assert detail.json()['grants'] == []
            check('新建草稿与默认不授权，保存后导航成功')
            capture('detail')
            page.get_by_role('button', name='访问范围', exact=True).click()
            expect(page.get_by_label('查找授权对象')).to_be_visible()
            page.get_by_role('checkbox', name='全局开放').check()
            page.get_by_role('button', name='保存访问范围', exact=True).click()
            expect(page.get_by_text('访问范围已保存', exact=True).first).to_be_visible()
            options = api.get(API + '/api/knowledge/permission-options', headers=headers).json()
            alice = next(u for u in options['users'] if u['username'] == 'alice')
            page.get_by_label('预览成员', exact=True).select_option(alice['id'])
            page.get_by_role('button', name='检查当前授权', exact=True).click()
            expect(page.locator('.preview-result')).to_contain_text('当前不允许阅读')
            check('真实四维授权保存，未发布预览仍拒绝')
            capture('permissions')
            page.get_by_role('button', name='版本历史', exact=True).click()
            expect(page.locator('.version-list li')).to_have_count(1)
            page.get_by_role('button', name='查看内容', exact=True).click()
            expect(page.locator('.version-content')).to_contain_text('交接前确认负责人')
            check('版本历史读取与正文溯源')
            capture('versions')
            page.get_by_role('button', name='附件', exact=False).first.click()
            page.get_by_label('选择附件', exact=True).set_input_files({'name': '交接清单.txt', 'mimeType': 'text/plain', 'buffer': '交接资料验收'.encode()})
            expect(page.locator('.attachment-list')).to_contain_text('交接清单.txt', timeout=20000)
            with page.expect_download() as download:
                page.locator('.attachment-list li').filter(has_text='交接清单.txt').get_by_role('button', name='下载', exact=True).click()
            assert download.value.suggested_filename == '交接清单.txt'
            check('FormData附件上传及Bearer blob下载')
            capture('attachments')
            page.get_by_role('link', name='编辑知识', exact=True).click()
            page.get_by_label('正文', exact=False).fill('第二版交接说明：确认复核人与处理记录。')
            page.get_by_role('link', name='返回知识详情', exact=True).click()
            expect(page.get_by_role('dialog')).to_contain_text('尚未保存')
            page.get_by_role('button', name='继续编辑', exact=True).click()
            page.get_by_role('button', name='保存知识', exact=True).click()
            expect(page.get_by_role('heading', name='知识详情', exact=True)).to_be_visible(timeout=20000)
            check('编辑未保存离开提示与新版本提交')
            page.get_by_role('link', name='返回知识列表', exact=True).click()
            page.get_by_label('搜索知识', exact=True).fill(name)
            expect(page.locator('.knowledge-table tbody tr')).to_have_count(1)
            capture('list')
            check('知识搜索及三宽度列表')
            page.goto(WEB + '/knowledge/import', wait_until='networkidle')
            page.get_by_label('选择导入文件', exact=True).set_input_files([
                {'name': name + '.txt', 'mimeType': 'text/plain', 'buffer': '导入文件包含用于操作验收的知识正文。'.encode()},
                {'name': name + '.doc', 'mimeType': 'application/msword', 'buffer': b'unsupported legacy format'},
            ])
            expect(page.locator('.selected-files li')).to_have_count(2)
            capture('import-selected')
            with page.expect_response('**/api/knowledge/import') as import_response:
                page.get_by_role('button', name='开始导入 2 个文件', exact=True).click()
            response = import_response.value
            assert response.status == 202, response.text()
            batch = response.json()
            report['batch_ids'].append(batch['id'])
            report['unit_ids'].extend(t['unit_id'] for t in batch.get('tasks', []) if t.get('unit_id'))
            expect(page.locator('.task-list li')).to_have_count(2, timeout=20000)
            expect(page.locator('.task-list')).to_contain_text('.doc')
            capture('import')
            check('真实混合批次提交、目录入口与文件进度渲染')
            assert not report['errors'], report['errors']
        finally:
            (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            browser.close()
    print(json.dumps({'checks': len(report['checks']), 'screens': len(report['screens']), 'errors': report['errors'], 'resources': report['unit_ids']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
