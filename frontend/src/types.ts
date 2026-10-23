export interface Role { id: string; role_name: string; role_code: string; description?: string; permission_codes?: string[] }
export interface User { id: string; username: string; display_name: string; email: string | null; status: 'active' | 'disabled'; department_id: string | null; department: {id: string; name: string} | null; roles: Role[]; created_at: string; updated_at: string }
export interface Department { id: string; code: string; name: string; parent_id: string | null; leader_id: string | null; sort_order: number; member_count: number; children: Department[] }
export interface Permission { code: string; name: string; permission_type: 'menu' | 'operation'; parent_code: string | null; path: string | null }
export interface Menu { code: string; name: string; path: string }
export interface Identity { user_info: User; permissions: string[] }
export interface PageResult<T> { items: T[]; total: number; page: number; page_size: number }
