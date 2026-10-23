import { ApiError, request, write, TOKEN_KEY } from './api'
import type { PageResult } from './types'

export interface Grant { target_type: 'global'|'department'|'role'|'user'; target_id: string }
export interface GrantOptions { departments: {id:string;name:string}[]; roles: {id:string;role_name:string}[]; users: {id:string;username:string;display_name:string;department_id:string|null}[] }
export interface Version { id:string; version_id:string; unit_id:string; version_number:number; status:string; task_id?:string|null; batch_id?:string|null; created_at:string; activated_at:string|null; is_active:boolean; content_hash:string; content?:string; attachments?:Attachment[]; chunks?: {id?:string;chunk_id:string;position?:Record<string,unknown>|number;chunk_index?:number;content?:string;metadata_json?:Record<string,unknown>}[] }
export interface Attachment { id:string; file_name:string; file_size:number; content_type:string; purpose:string; unit_id:string; version_id:string; download_url:string; image_url?:string }
export interface Unit { id:string;unit_id:string;unit_code:string;title:string;summary:string;category:string;tags:string[];status:string;creator_id:string;creator_name:string;active_version_id:string|null;source_file_name:string|null;file_type:string|null;file_size:number|null;created_at:string;updated_at:string;permission_summary:Record<string,number>;can_edit:boolean;can_delete:boolean;can_manage_permissions:boolean;can_manage_versions:boolean;can_attach:boolean }
export interface UnitDetail extends Unit { content:string;active_version:Version|null;latest_version:Version|null;attachments:Attachment[];grants:Grant[];task_id?:string;batch_id?:string;is_maintenance_view?:boolean }
export interface UnitInput {title:string;content:string;summary:string;category:string;tags:string[];grants?:Grant[]}
export interface ImportTask { id:string;batch_id:string;unit_id:string|null;version_id:string|null;file_name:string;relative_path:string;file_size:number;status:string;stage:string;attempts:number;max_attempts:number;error_code:string|null;error_message:string|null;retry_at:string|null;progress:{percent?:number;chunk_count?:number;warnings?:string[]};can_retry:boolean;created_at:string;updated_at:string }
export interface ImportBatch { id:string;batch_id:string;status:string;file_count:number;counts:Record<string,number>;created_at:string;updated_at:string;tasks:ImportTask[] }
export interface Capabilities { [key:string]:unknown }
const query = (params:Record<string,string|number>) => new URLSearchParams(Object.entries(params).filter(([,v])=>v!=='').map(([k,v])=>[k,String(v)]))
export const knowledge = {
 list: (params:Record<string,string|number>)=>request<PageResult<Unit>>(`/knowledge/units?${query(params)}`),
 categories: ()=>request<{items:string[]}>('/knowledge/categories'),
 detail: (id:string)=>request<UnitDetail>(`/knowledge/units/${id}`),
 create: (body:UnitInput)=>write<UnitDetail>('/knowledge/units',body),
 update: (id:string,body:UnitInput)=>write<UnitDetail>(`/knowledge/units/${id}`,body,'PUT'),
 remove: (ids:string[])=>write('/knowledge/units',{unit_ids:ids},'DELETE'),
 status: (id:string,status:string)=>write(`/knowledge/units/${id}/status`,{status}),
 versions: (id:string)=>request<{items:Version[]}>(`/knowledge/units/${id}/versions`),
 version: (id:string,versionId:string)=>request<Version>(`/knowledge/units/${id}/versions/${versionId}`),
 activate: (id:string,versionId:string)=>write(`/knowledge/units/${id}/versions/${versionId}/activate`),
 rebuild: (id:string,versionId:string)=>write<UnitDetail>(`/knowledge/units/${id}/versions/${versionId}/rebuild`),
 options: (search='')=>request<GrantOptions>(`/knowledge/permission-options?search=${encodeURIComponent(search)}`),
 permissions: (id:string,grants:Grant[])=>write(`/knowledge/units/${id}/permissions`,{grants}),
 preview: (id:string,userId:string)=>write<{authorized_unit_ids:string[];unauthorized_unit_ids:string[]}>('/knowledge/preview-permissions',{user_id:userId,unit_ids:[id]}),
 attach: (id:string,file:File,versionId?:string)=>{const body=new FormData();body.append('file',file);if(versionId)body.append('version_id',versionId);return request<Attachment>(`/knowledge/units/${id}/attachments`,{method:'POST',body,signal:AbortSignal.timeout(120000)})},
 detach: (id:string,fileId:string)=>write(`/knowledge/units/${id}/attachments/${fileId}`,undefined,'DELETE'),
 capabilities: ()=>request<Capabilities>('/knowledge/import/capabilities'),
 batches: (page=1)=>request<PageResult<ImportBatch>>(`/knowledge/batches?page=${page}&page_size=10`),
 batch: (id:string)=>request<ImportBatch>(`/knowledge/batches/${id}`),
 retry: (id:string)=>write<ImportTask>(`/knowledge/tasks/${id}/retry`),
}
export function uploadBatch(body:FormData,onProgress:(percent:number)=>void,signal?:AbortSignal):Promise<ImportBatch> {
 return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest();xhr.open('POST','/api/knowledge/import');xhr.timeout=180000
  const token=sessionStorage.getItem(TOKEN_KEY);if(token)xhr.setRequestHeader('Authorization',`Bearer ${token}`)
  const abort=()=>xhr.abort();signal?.addEventListener('abort',abort,{once:true})
  xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(Math.round(e.loaded/e.total*100))}
  xhr.onload=()=>{let body:ImportBatch & {detail?:string};try{body=JSON.parse(xhr.responseText)}catch{reject(new ApiError(xhr.status,'上传响应不可用，请重试。'));return}if(xhr.status>=200&&xhr.status<300)resolve(body);else reject(new ApiError(xhr.status,typeof body.detail==='string'?body.detail:'上传失败，请检查文件后重试。'))}
  xhr.onerror=()=>reject(new ApiError(0,'上传中断，可使用同一批文件重试。'));xhr.ontimeout=()=>reject(new ApiError(0,'上传超时，可使用同一批文件重试。'));xhr.onabort=()=>reject(new DOMException('上传已中断','AbortError'));xhr.onloadend=()=>signal?.removeEventListener('abort',abort)
  if(signal?.aborted){reject(new DOMException('上传已中断','AbortError'));return}xhr.send(body)
 })
}
export const unitStatus:Record<string,string>={draft:'草稿',published:'已发布',disabled:'已停用',deleted:'已删除'}
export const versionStatus:Record<string,string>={pending:'等待构建',processing:'构建中',building:'构建中',ready:'已就绪',failed:'构建失败',archived:'已归档'}
export const taskStatus:Record<string,string>={pending:'等待处理',processing:'处理中',completed:'已完成',failed:'失败',cancelled:'已取消'}
export const taskStage:Record<string,string>={uploaded:'已接收',parsing:'解析正文',images:'处理图片',chunking:'拆分正文',embedding:'建立语义索引',indexing:'保存索引',ready:'版本已就绪',retry_wait:'等待自动重试',failed:'处理失败',cancelled:'已取消'}
export function fileSize(bytes:number|null|undefined){if(bytes==null)return '—';if(bytes<1024)return `${bytes} B`;if(bytes<1024*1024)return `${(bytes/1024).toFixed(1)} KB`;return `${(bytes/1024/1024).toFixed(1)} MB`}
export function displayTime(value:string){if(!value)return '—';const d=new Date(value);return Number.isNaN(d.getTime())?'—':new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d)}
export function grantSummary(counts:Record<string,number>){const labels:Record<string,string>={department:'部门',role:'角色',user:'个人'};return [counts?.global?'全局开放':'',...Object.entries(labels).filter(([key])=>counts?.[key]).map(([key,label])=>`${label} ${counts[key]}`)].filter(Boolean).join(' · ')||'未开放阅读'}
