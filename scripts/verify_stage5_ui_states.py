"""Deliberate transport/state injections, separate from actual model evidence."""
import json
import os
from pathlib import Path
from uuid import uuid4
from playwright.sync_api import expect, sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evidence/stage5/ui'
WEB=os.getenv('STAGE5_WEB_ORIGIN','http://127.0.0.1:5185')
API=os.getenv('STAGE5_API_ORIGIN','http://127.0.0.1:8104')

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    credentials=json.loads((ROOT/'var/setup/stage2-accounts.json').read_text(encoding='utf-8'))
    report={'checks':[],'screens':[],'errors':[],'kind':'explicit_browser_injected_transport_states','sessions':[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        context=browser.new_context(viewport={'width':1440,'height':900})
        login=context.request.post(API+'/api/auth/login',data={'username':'alice','password':credentials['alice']})
        assert login.ok
        token=login.json()['access_token'];headers={'Authorization':'Bearer '+token}
        context.add_init_script('sessionStorage.setItem("kb-platform-token",'+json.dumps(token)+')')
        page=context.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
        session=context.request.post(API+'/api/ai/chat/sessions',headers=headers,data={'title':'S5状态验证_'+uuid4().hex[:8]}).json()
        sid=session['id'];request_id=str(uuid4())
        report['sessions'].append(sid)
        def frame(kind,data):return 'event: '+kind+'\r\ndata: '+json.dumps({'request_id':request_id,'session_id':sid,**data},ensure_ascii=False)+'\r\n\r\n'
        def select():
            page.locator('.chat-session-select').filter(has_text=session['title']).click()
            expect(page.locator('#chat-question')).to_be_visible()
        def capture(name):
            for width in (1440,768,390):
                page.set_viewport_size({'width':width,'height':900})
                page.evaluate('document.fonts.ready')
                page.screenshot(path=str(OUT/f'{name}-{width}.png'),full_page=True)
                overflow=page.evaluate('document.documentElement.scrollWidth>innerWidth')
                report['screens'].append({'name':name,'width':width,'overflow':overflow,'kind':'injected'})
                assert not overflow
            page.set_viewport_size({'width':1440,'height':900})
        try:
            page.goto(WEB+'/chat',wait_until='networkidle');select()
            parser_result=page.evaluate("""async()=>{const {SSEFrames}=await import('/src/chat.ts');const events=[];const p=new SSEFrames(e=>events.push(e));const text=': heartbeat\\r\\n\\r\\nevent: delta\\r\\ndata: {"text":"中文✓"}\\r\\n\\r\\nevent: end\\ndata: {"status":"completed"}\\n\\n';const bytes=new TextEncoder().encode(text);const d=new TextDecoder();for(const byte of bytes)p.push(d.decode(new Uint8Array([byte]),{stream:true}));p.push(d.decode(),true);if(events.length!==2||events[0].data.text!=='中文✓'||events[1].type!=='end')throw Error('SSE framing mismatch');return events.map(x=>x.type)}""")
            assert parser_result==['delta','end']
            report['checks'].append('逐字节UTF8中文和CRLF跨块，心跳忽略，end解析')
            unsafe='# 测试标题\n\n**明确依据**\n\n<script>window.__unsafe=true</script><img src="https://example.test/track" onerror="window.__unsafe=true">\n\n![外部图片](https://example.test/track)\n\n[危险链接](javascript:alert(1))\n\n- 一条说明\n\n```js\nconst code = 1\n```'
            stream=frame('meta',{})+frame('delta',{'text':unsafe})
            page.route('**/api/ai/chat/stream',lambda r:r.fulfill(status=200,content_type='text/event-stream',body=stream))
            page.locator('#chat-question').fill('安全渲染状态验证');page.get_by_role('button',name='发送问题',exact=True).click()
            expect(page.locator('.chat-turn').last).to_contain_text('回答连接已中断',timeout=20000)
            assert page.locator('.chat-markdown img,.chat-markdown script,.chat-markdown iframe').count()==0
            assert not page.evaluate('!!window.__unsafe')
            report['checks'].append('缺失end断流转失败并清空不完整回答')
            page.unroute('**/api/ai/chat/stream')
            unsafe_turn={'request_id':request_id,'status':'completed','created_at':'2026-10-22T06:00:00Z','user':{'content':'明确标注的Markdown安全注入测试'},'assistant':{'content':unsafe,'sources':[]}}
            page.route('**/api/ai/chat/sessions/'+sid+'/messages',lambda r:r.fulfill(status=200,content_type='application/json',body=json.dumps({'session_id':sid,'items':[unsafe_turn]})))
            select();expect(page.locator('.chat-markdown strong')).to_have_text('明确依据')
            assert page.locator('.chat-markdown img,.chat-markdown script,.chat-markdown iframe,.chat-markdown a[href^="javascript:"]').count()==0
            assert page.locator('.chat-markdown pre code').count()==1
            assert not page.evaluate('!!window.__unsafe')
            capture('markdown-safe')
            page.unroute('**/api/ai/chat/sessions/'+sid+'/messages')
            report['checks'].append('注入恶意Markdown，标题列表代码正常，HTML图片危险链接被清除')
            external_turn={**unsafe_turn,'assistant':{'content':'内部知识回答','sources':[]},'external_sources':[{'source_type':'external','title':'公开参考','snippet':'仅作外部参考','url':'https://example.org/reference'},{'source_type':'external','title':'危险地址','url':'javascript:alert(1)'}]}
            page.route('**/api/ai/chat/sessions/'+sid+'/messages',lambda r:r.fulfill(status=200,content_type='application/json',body=json.dumps({'session_id':sid,'items':[external_turn]})))
            select();expect(page.locator('.chat-external-sources')).to_contain_text('不作为内部制度依据')
            expect(page.locator('.chat-external-sources a')).to_have_count(1)
            expect(page.locator('.chat-external-sources a')).to_have_attribute('rel','noopener noreferrer')
            page.unroute('**/api/ai/chat/sessions/'+sid+'/messages')
            report['checks'].append('注入外部来源清楚标注，安全新标签链接，危险协议丢弃')
            # The raw parser can deliver valid end, but the DOM security exercise needs a held stream.
            # Intercept history only for explicitly declared terminal-state visual checks.
            for status,name in [('low_confidence','low-confidence'),('error','stream-error'),('restricted','permission-changed')]:
                turn={'request_id':request_id,'status':status,'created_at':'2026-10-22T06:00:00Z','user':{'content':'明确标注的界面状态验证','redacted':status=='restricted'},'assistant':{'content':'','sources':[],'redacted':status=='restricted'}}
                page.route('**/api/ai/chat/sessions/'+sid+'/messages',lambda r,request,t=turn:r.fulfill(status=200,content_type='application/json',body=json.dumps({'session_id':sid,'items':[t]})))
                select();expect(page.locator('.chat-turn-status').last).not_to_have_text('生成中')
                capture(name);page.unroute('**/api/ai/chat/sessions/'+sid+'/messages')
                report['checks'].append('注入终态 '+status+' 的文案和三宽度')
            page.route('**/api/ai/chat/sessions/'+sid+'/messages',lambda r:r.abort('failed'))
            select();expect(page.locator('.chat-timeline')).to_contain_text('连接暂时不可用')
            capture('history-error');page.unroute('**/api/ai/chat/sessions/'+sid+'/messages')
            page.get_by_role('button',name='重新加载会话',exact=True).click();expect(page.locator('.chat-start')).to_be_visible()
            report['checks'].append('注入历史网络错误与真实重试恢复')
            page.evaluate("""()=>{const original=window.fetch.bind(window);window.__streamNative=original;window.__streamMode='normal';window.fetch=async(input,options)=>{if(String(input)!=='/api/ai/chat/stream')return original(input,options);const body=JSON.parse(options.body);const requestId=crypto.randomUUID();let controller;const stream=new ReadableStream({start(c){controller=c},cancel(){}});window.__lateStream={controller,body,requestId};const frame=(type,data)=>new TextEncoder().encode('event: '+type+'\\r\\ndata: '+JSON.stringify({request_id:requestId,session_id:body.session_id,...data})+'\\r\\n\\r\\n');window.__emitLate=(type,data)=>{try{controller.enqueue(frame(type,data))}catch{}};if(window.__streamMode==='late-meta'){await new Promise(r=>setTimeout(r,700))}window.__emitLate('meta',{});window.__emitLate('delta',{text:'**注入中的中文回答**'});return new Response(stream,{status:200,headers:{'Content-Type':'text/event-stream'}})}}""")
            select();page.locator('#chat-question').fill('流式加载状态验证');page.get_by_role('button',name='发送问题',exact=True).click()
            expect(page.locator('.chat-markdown strong')).to_have_text('注入中的中文回答')
            capture('streaming')
            page.get_by_role('button',name='停止生成',exact=True).click()
            expect(page.locator('.chat-turn-status').last).to_have_text('已停止')
            page.evaluate("window.__emitLate('delta',{text:'迟到内容不应出现'});window.__emitLate('end',{status:'completed',persisted:true});window.__lateStream.controller.close()")
            assert '迟到内容' not in page.locator('.chat-conversation').inner_text()
            report['checks'].append('注入真实ReadableStream加载、停止后迟到delta及end不回填')
            page.evaluate("window.__streamMode='late-meta'")
            select();page.locator('#chat-question').fill('延迟meta停止验证');page.get_by_role('button',name='发送问题',exact=True).click();page.get_by_role('button',name='停止生成',exact=True).click()
            page.wait_for_timeout(900)
            page.evaluate("window.__emitLate('end',{status:'completed',persisted:true});window.__lateStream.controller.close()")
            assert '注入中的中文回答' not in page.locator('.chat-conversation').inner_text()
            report['checks'].append('注入延迟meta：停止后识别request id并取消，旧回答不恢复')
            secondary=context.request.post(API+'/api/ai/chat/sessions',headers=headers,data={'title':'S5切换验证_'+uuid4().hex[:8]}).json()
            report['sessions'].append(secondary['id'])
            page.evaluate("window.__streamMode='normal'")
            page.get_by_role('button',name='刷新历史会话',exact=True).click()
            expect(page.locator('.chat-session-select').filter(has_text=secondary['title'])).to_be_visible()
            select();page.locator('#chat-question').fill('需要保留的未发送问题')
            page.locator('.chat-session-select').filter(has_text=secondary['title']).click()
            expect(page.get_by_role('dialog')).to_contain_text('尚未发送')
            page.get_by_role('button',name='继续填写',exact=True).click()
            assert page.locator('#chat-question').input_value()=='需要保留的未发送问题'
            page.get_by_role('link',name='个人中心',exact=True).first.click()
            expect(page.get_by_role('dialog')).to_contain_text('尚未发送')
            page.get_by_role('button',name='继续填写',exact=True).click()
            assert page.url.endswith('/chat')
            page.locator('#chat-question').fill('')
            report['checks'].append('未发送问题切换会话和导航守卫保留草稿')
            select();page.locator('#chat-question').fill('会话切换迟到事件验证');page.get_by_role('button',name='发送问题',exact=True).click()
            expect(page.locator('.chat-markdown strong')).to_have_text('注入中的中文回答')
            page.locator('.chat-session-select').filter(has_text=secondary['title']).click()
            expect(page.locator('.chat-start')).to_be_visible()
            page.evaluate("window.__emitLate('delta',{text:'前一会话的迟到回答'});window.__emitLate('end',{status:'completed',persisted:true});window.__lateStream.controller.close()")
            assert '前一会话的迟到回答' not in page.locator('.chat-conversation').inner_text()
            report['checks'].append('注入切换会话迟到事件不写入新会话')
            page.set_viewport_size({'width':390,'height':700})
            expect(page.get_by_role('button',name='发送问题',exact=True)).to_be_in_viewport()
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
            page.screenshot(path=str(OUT/'mobile-short-390x700.png'),full_page=True)
            report['checks'].append('390×700较短手机视口输入和发送可见')
            page.set_viewport_size({'width':1440,'height':900})
            page.evaluate("window.__streamMode='normal'")
            select();page.locator('#chat-question').fill('离开页面时取消验证');page.get_by_role('button',name='发送问题',exact=True).click()
            expect(page.locator('.chat-markdown strong')).to_have_text('注入中的中文回答')
            page.get_by_role('link',name='个人中心',exact=True).first.click()
            expect(page.get_by_role('heading',name='个人中心',exact=True)).to_be_visible()
            page.evaluate("window.__emitLate('delta',{text:'离开后的迟到回答'});window.__emitLate('end',{status:'completed',persisted:true});window.__lateStream.controller.close();window.fetch=window.__streamNative")
            assert '离开后的迟到回答' not in page.locator('body').inner_text()
            report['checks'].append('注入导航卸载期间迟到回答不回填')
            assert not report['errors'],report['errors']
        finally:
            for session_id in report['sessions']:
                result=context.request.delete(API+'/api/ai/chat/sessions/'+session_id,headers=headers)
                assert result.status in (204,404)
            report['cleanup']='exact own session deleted'
            (OUT/'states.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()
    print(json.dumps({'checks':len(report['checks']),'errors':report['errors']},ensure_ascii=False))

if __name__=='__main__':main()
