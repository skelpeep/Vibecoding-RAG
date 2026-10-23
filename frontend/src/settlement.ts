import { request, write } from './api'
import type { ChatSource } from './chat'
export interface FAQ { id:string; question:string; answer:string|null; status:string; revision:number; frequency:number; hit_count:number; source_valid:boolean; sources:ChatSource[]; cache_state:string; updated_at:string; mining_mode:string }
export interface Gap { id:string; question_pattern:string; sample_questions:string[]; ask_count:number; status:string; resolved_unit_id:string|null; last_asked_at:string|null }
export interface Page<T> { items:T[]; total:number; page:number; page_size:number }
export interface Dashboard { range:{start:string;end:string;timezone:string;bucket:string}; metrics:Record<string,number|null>; trends:{date:string;visits:number;tokens:number;unknown_usage:number;average_response_ms:number|null}[]; questions:{question:string;count:number}[]; units:{unit_id:string;title:string;count:number}[]; latency:{label:string;count:number}[]; definitions:Record<string,string> }
export const settlement = {
  faqs:(status:string,page=1)=>request<Page<FAQ>>(`/settlement/faqs?status=${status}&page=${page}`),
  gaps:(status:string,page=1)=>request<Page<Gap>>(`/settlement/knowledge-gaps?status=${status}&page=${page}`),
  mine:()=>request<{created_faqs:number;created_gaps:number;mode:string;truncated:boolean}>('/settlement/mine',{method:'POST',signal:AbortSignal.timeout(300000)}),
  review:(row:FAQ,action:string,answer?:string)=>write<FAQ>(`/settlement/faqs/${row.id}/review`,{action,revision:row.revision,...(answer?{edited_answer:answer}:{})}),
  withdraw:(row:FAQ)=>write(`/settlement/faqs/${row.id}/withdraw`,{revision:row.revision}),
  edit:(row:FAQ,answer:string)=>write(`/settlement/faqs/${row.id}`,{revision:row.revision,answer},'PUT'),
  state:(row:Gap,status:string,request_id?:string)=>write(`/settlement/knowledge-gaps/${row.id}/status`,{status,request_id}),
}
export const number = (value:number|null|undefined, digits=0) => value==null?'—':new Intl.NumberFormat('zh-CN',{maximumFractionDigits:digits,minimumFractionDigits:digits}).format(value)
