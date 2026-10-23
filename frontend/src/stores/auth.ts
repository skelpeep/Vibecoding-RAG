import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, TOKEN_KEY, write } from '../api'
import type { Menu, User } from '../types'

export const useAuth = defineStore('auth', () => {
  const user = ref<User | null>(null), permissions = ref<string[]>([]), menus = ref<Menu[]>([])
  const has = (code: string) => permissions.value.includes(code)
  let pending: Promise<void> | null = null
  function clear() { sessionStorage.removeItem(TOKEN_KEY); user.value = null; permissions.value = []; menus.value = [] }
  async function refresh() {
    if (!sessionStorage.getItem(TOKEN_KEY)) { clear(); return }
    if (pending) return pending
    const requestedToken = sessionStorage.getItem(TOKEN_KEY)
    pending = (async () => { const [identity, navigation] = await Promise.all([api.me(), api.menus()]); if(sessionStorage.getItem(TOKEN_KEY)!==requestedToken)return; user.value = identity.user_info; permissions.value = identity.permissions; menus.value = navigation.items })().finally(() => { pending = null })
    return pending
  }
  async function login(username: string, password: string) { const identity = await api.login(username,password); sessionStorage.setItem(TOKEN_KEY,identity.access_token); user.value = identity.user_info; permissions.value = identity.permissions; await refresh() }
  async function logout() { try { await write('/auth/logout') } finally { clear() } }
  function home() { if (has('menu:org')) { if (has('org:user:read')) return '/org/users'; if (has('org:role:read')) return '/org/roles'; if (has('org:department:read')) return '/org/departments' } if (has('menu:knowledge')) return '/knowledge'; return '/profile' }
  return {user, permissions, menus, has, clear, refresh, login, logout, home}
})
