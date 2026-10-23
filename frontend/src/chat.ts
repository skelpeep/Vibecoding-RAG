import { ApiError, TOKEN_KEY, request, write } from './api'

export interface ChatSession { id:string; title:string; status:string; created_at:string; updated_at:string }
export interface ChatSource { unit_id:string; version_id:string; chunk_id:string; title:string; position:unknown; snippet?:string; citation_url?:string; citation?:number|string }
export interface ExternalSource { title:string; snippet?:string; url:string; source_type:'external' }
export interface ChatTurn { cache_status?:string; request_id:string; status:string; user:{content:string;redacted?:boolean}; assistant:{content:string;sources:ChatSource[];redacted?:boolean}; created_at:string; notice?:string; noticeCode?:string; reason?:string; external_sources?:ExternalSource[]; permission_hint?:{code?:string;reason?:string;message?:string} }
export interface ChatEvent { type:string; data:Record<string, unknown> }
export const chatApi = {
  sessions:(page=1)=>request<{items:ChatSession[];total:number;page:number;page_size:number}>(`/ai/chat/sessions?page=${page}&page_size=30`),
  create:()=>write<ChatSession>('/ai/chat/sessions',{}),
  remove:(id:string)=>write(`/ai/chat/sessions/${encodeURIComponent(id)}`,undefined,'DELETE'),
  history:(id:string,signal?:AbortSignal)=>request<{items:ChatTurn[];session_id:string}>(`/ai/chat/sessions/${encodeURIComponent(id)}/messages`,{signal}),
  cancel:(id:string)=>write(`/ai/chat/requests/${encodeURIComponent(id)}/cancel`),
  citation:(requestId:string,chunkId:string,signal?:AbortSignal)=>request<ChatSource & {content?:string}>(`/ai/chat/requests/${encodeURIComponent(requestId)}/citations/${encodeURIComponent(chunkId)}`,{signal}),
}

/** Incremental SSE framing: UTF-8 is decoded separately; CRLF may cross reads. */
export class SSEFrames {
  private buffer=''
  constructor(private onEvent:(event:ChatEvent)=>void) {}
  push(text:string,flush=false) {
    this.buffer+=text
    const boundary=/\r\n\r\n|\n\n|\r\r/
    let match:RegExpExecArray|null
    while((match=boundary.exec(this.buffer))) {
      const frame=this.buffer.slice(0,match.index)
      this.buffer=this.buffer.slice(match.index+match[0].length)
      this.dispatch(frame)
    }
    if(flush&&this.buffer.trim()){this.dispatch(this.buffer);this.buffer=''}
  }
  private dispatch(frame:string) {
    let type='message';const data:string[]=[]
    for(const line of frame.split(/\r\n|\n|\r/)) {
      if(line.startsWith(':'))continue
      const i=line.indexOf(':');const field=i<0?line:line.slice(0,i)
      const value=i<0?'':line.slice(i+1).replace(/^ /,'')
      if(field==='event')type=value
      if(field==='data')data.push(value)
    }
    if(!data.length)return
    try {this.onEvent({type,data:JSON.parse(data.join('\n')) as Record<string,unknown>})}
    catch(error){if(error instanceof SyntaxError)throw new ApiError(0,'回答数据不完整，请重新提问。');throw error}
  }
}

export async function streamChat(question:string,sessionId:string,signal:AbortSignal,onEvent:(event:ChatEvent)=>void) {
  const token=sessionStorage.getItem(TOKEN_KEY)
  const response=await fetch('/api/ai/chat/stream',{method:'POST',headers:{'Content-Type':'application/json','Accept':'text/event-stream',...(token?{Authorization:`Bearer ${token}`}:{})},body:JSON.stringify({question,session_id:sessionId}),signal})
  if(!response.ok) {
    if(response.status===401) {await request('/auth/me',{signal}).catch(()=>{})}
    const body=await response.json().catch(()=>({}))
    throw new ApiError(response.status,typeof body.detail==='string'?body.detail:'回答未能开始，请稍后重试。')
  }
  if(!response.body||!response.headers.get('content-type')?.includes('text/event-stream'))throw new ApiError(0,'问答连接未返回有效的回答，请重试。')
  const reader=response.body.getReader(),decoder=new TextDecoder('utf-8'),parser=new SSEFrames(onEvent)
  try {while(true){const {done,value}=await reader.read();if(done)break;parser.push(decoder.decode(value,{stream:true}))}parser.push(decoder.decode(),true)}
  finally {await reader.cancel().catch(()=>{});reader.releaseLock()}
}

export function sourcePosition(position:unknown):string {
  if(typeof position==='string')return position
  if(!position||typeof position!=='object')return '正文切片'
  const p=position as Record<string,unknown>;const parts=[]
  if(p.page!==undefined)parts.push(`第 ${p.page} 页`)
  if(p.paragraph!==undefined)parts.push(`第 ${p.paragraph} 段`)
  if(p.block!==undefined)parts.push(`正文第 ${Number(p.block)+1} 块`)
  if(p.line_start!==undefined)parts.push(`第 ${p.line_start}${p.line_end!==undefined&&p.line_end!==p.line_start?`–${p.line_end}`:''} 行`)
  if(p.char_start!==undefined&&p.char_end!==undefined)parts.push(`字符 ${p.char_start}–${p.char_end}`)
  if(p.chunk_index!==undefined)parts.push(`切片 ${Number(p.chunk_index)+1}`)
  return parts.join(' · ')||'正文切片'
}
export function chatTime(value:string):string {const utc=/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(value)?`${value}Z`:value;const date=new Date(utc);return Number.isNaN(date.getTime())?'时间未提供':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(date)}
export function safeExternalSources(value:unknown):ExternalSource[] {
  if(!Array.isArray(value))return []
  return value.slice(0,8).filter(item=>{if(!item||typeof item.url!=='string'||item.url.length>2048||typeof item.title!=='string')return false;try{const url=new URL(item.url);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password}catch{return false}}).map(item=>({source_type:'external',title:item.title.slice(0,200),snippet:typeof item.snippet==='string'?item.snippet.slice(0,500):'',url:item.url}))
}
