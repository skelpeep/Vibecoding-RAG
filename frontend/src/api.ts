import type { Department, Identity, Menu, PageResult, Permission, Role, User } from './types'

export const TOKEN_KEY = 'kb-platform-token'
export class ApiError extends Error { constructor(public status: number, message: string) { super(message) } }
let unauthorizedHandler = () => {}
let forbiddenHandler = () => {}
export function setAuthHandlers(unauthorized: () => void, forbidden: () => void) { unauthorizedHandler = unauthorized; forbiddenHandler = forbidden }
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const token = sessionStorage.getItem(TOKEN_KEY)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let response: Response
  try { response = await fetch(`/api${path}`, { ...options, headers, signal: options.signal ?? AbortSignal.timeout(15000) }) }
  catch (error) { if (error instanceof DOMException && error.name === 'AbortError') throw error; throw new ApiError(0, '连接暂时不可用，请检查网络后重试。') }
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') unauthorizedHandler()
    if (response.status === 403) forbiddenHandler()
    const detail = typeof body.detail === 'string' ? body.detail : response.status === 422 ? '请检查填写内容，编码、必填项或组织关系不符合要求。' : '操作未完成，请稍后重试。'
    throw new ApiError(response.status, detail)
  }
  return body as T
}
export const write = <T>(path: string, body?: unknown, method = 'POST') => request<T>(path, {method, body: body === undefined ? undefined : JSON.stringify(body)})
export const api = {
  login: (username: string, password: string) => write<Identity & {access_token: string}>('/auth/login', {username, password}),
  me: () => request<Identity>('/auth/me'), menus: () => request<{items: Menu[]}>('/auth/menus'),
  users: (params: Record<string, string | number> = {}) => request<PageResult<User>>(`/org/users?${new URLSearchParams(Object.entries(params).map(([k,v]) => [k,String(v)]))}`),
  roles: () => request<{items: Role[]}>('/org/roles'), departments: () => request<{items: Department[]}>('/org/departments'),
  permissions: () => request<{items: Permission[]}>('/org/permissions'),
}
export async function allUsers() {
  let page = 1, items: User[] = [], total = 0
  do { const result = await api.users({page, page_size: 100}); items = items.concat(result.items); total = result.total; page++ } while(items.length < total)
  return items
}
export const errorText = (error: unknown) => error instanceof Error ? error.message : '操作未完成，请重试。'
export async function authorizedBlob(path: string, signal?:AbortSignal): Promise<Blob> {
  const headers = new Headers(), token = sessionStorage.getItem(TOKEN_KEY)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let response: Response
  try { response = await fetch(`/api${path}`, {headers, signal: signal||AbortSignal.timeout(120000)}) }
  catch { throw new ApiError(0, '文件下载中断，请重试。') }
  if (!response.ok) {
    if (response.status === 401) unauthorizedHandler()
    if (response.status === 403) forbiddenHandler()
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, typeof body.detail === 'string' ? body.detail : '文件不存在或已无权访问。')
  }
  return await response.blob()
}
export async function authorizedDownload(path: string, filename: string): Promise<void> {
  const url = URL.createObjectURL(await authorizedBlob(path)), link = document.createElement('a')
  link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function flattenDepartments(nodes: Department[], depth = 0): (Department & {depth: number})[] { return nodes.flatMap(node => [{...node, depth}, ...flattenDepartments(node.children, depth + 1)]) }
export function formatDate(value: string) { return new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value)).replaceAll('/','-') }
