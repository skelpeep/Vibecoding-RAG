<script setup lang="ts">
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Users, Network, ShieldCheck, BookOpen, MessageSquare, ChartNoAxesCombined, Archive, Menu as MenuIcon, X, LogOut, ChevronRight, UserRound } from 'lucide-vue-next'
import { useAuth } from '../stores/auth'
import BrandMark from './BrandMark.vue'
import UserAvatar from './UserAvatar.vue'
const auth = useAuth(), route = useRoute(), router = useRouter(), open = ref(false)
const sidebar=ref<HTMLElement|null>(null)
let returnFocus:HTMLElement|null=null,previousOverflow=''
watch(open,async visible=>{if(visible){returnFocus=document.activeElement as HTMLElement;previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';await nextTick();sidebar.value?.querySelector<HTMLElement>('a,button')?.focus()}else{document.body.style.overflow=previousOverflow;returnFocus?.focus()}})
const nav = computed(() => [
  {path:'/org/users',label:'用户管理',icon:Users,menu:'menu:org',permission:'org:user:read'},
  {path:'/org/roles',label:'角色与权限',icon:ShieldCheck,menu:'menu:org',permission:'org:role:read'},
  {path:'/org/departments',label:'部门管理',icon:Network,menu:'menu:org',permission:'org:department:read'},
].filter(item => auth.menus.some(m => m.code === item.menu) && auth.has(item.permission)))
const businessNav = computed(() => [
  {path:'/knowledge',label:'知识维护',icon:BookOpen,menu:'menu:knowledge'}, {path:'/chat',label:'AI 问答',icon:MessageSquare,menu:'menu:ai'},
  {path:'/dashboard',label:'数据看板',icon:ChartNoAxesCombined,menu:'menu:dashboard'}, {path:'/settlement',label:'知识沉淀',icon:Archive,menu:'menu:settlement'},
].filter(item => auth.menus.some(m => m.code === item.menu)))
watch(() => route.fullPath, () => { open.value = false })
async function refreshIdentity() {
  if (document.visibilityState !== 'visible') return
  try { await auth.refresh(); if ((route.meta.permission && !auth.has(String(route.meta.permission))) || (route.meta.menu && !auth.has(String(route.meta.menu)))) await router.replace('/forbidden') } catch { /* requests handle availability and expired identity */ }
}
function escape(e: KeyboardEvent) { if(e.key === 'Escape') open.value = false; if(open.value&&e.key==='Tab'){const targets=Array.from(sidebar.value?.querySelectorAll<HTMLElement>('a,button:not([disabled])')||[]).filter(el=>el.getClientRects().length);const first=targets[0],last=targets.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}} }
function resize(){if(window.innerWidth>1100)open.value=false}
let interval: ReturnType<typeof setInterval>
onMounted(() => { document.addEventListener('visibilitychange',refreshIdentity); window.addEventListener('focus',refreshIdentity); window.addEventListener('keydown',escape);window.addEventListener('resize',resize); interval=setInterval(refreshIdentity,60000) })
onUnmounted(() => {document.removeEventListener('visibilitychange',refreshIdentity);window.removeEventListener('focus',refreshIdentity);window.removeEventListener('keydown',escape);window.removeEventListener('resize',resize);if(open.value)document.body.style.overflow=previousOverflow;clearInterval(interval)})
async function logout() { await auth.logout().catch(() => {}); await router.replace('/login') }
</script>
<template>
  <div class="app-frame">
    <button v-if="open" class="nav-backdrop" tabindex="-1" aria-label="关闭导航" @click="open=false"></button>
    <aside ref="sidebar" class="sidebar" :class="{'mobile-open':open}" :role="open?'dialog':undefined" :aria-modal="open?true:undefined" :aria-label="open?'工作区导航':undefined">
      <button v-if="open" class="icon-button nav-close" aria-label="关闭导航" @click="open=false"><X :size="19"/></button>
      <RouterLink class="brand" :to="auth.home()"><BrandMark /><span>知识库管理平台</span></RouterLink>
      <div class="workspace"><span class="workspace-dot"></span>组织工作区</div>
      <nav aria-label="主导航"><div v-if="nav.length" class="nav-label">组织与权限</div><RouterLink v-for="item in nav" :key="item.path" :to="item.path" class="nav-item" active-class="active"><component :is="item.icon" :size="17" :stroke-width="1.6" />{{ item.label }}</RouterLink><div v-if="businessNav.length" class="nav-label business-label">知识工作区</div><RouterLink v-for="item in businessNav" :key="item.path" :to="item.path" class="nav-item" active-class="active"><component :is="item.icon" :size="17" :stroke-width="1.6" />{{ item.label }}</RouterLink></nav>
      <div class="sidebar-bottom"><div class="sidebar-note"><BookOpen :size="17" /><span>让知识找到需要它的人</span></div><RouterLink to="/profile" class="account-row" aria-label="打开个人中心"><UserAvatar :name="auth.user?.display_name || '我'" :identity="auth.user?.id || ''" /><span class="account-name"><strong>{{ auth.user?.display_name || '当前账号' }}</strong><small>{{ auth.user?.department?.name || '未分配部门' }}</small></span><ChevronRight :size="15" /></RouterLink></div>
    </aside>
    <header class="topbar"><div class="breadcrumb"><button class="icon-button mobile-menu" :aria-expanded="open" aria-label="展开导航" @click="open=!open"><X v-if="open" :size="19"/><MenuIcon v-else :size="19"/></button><span class="crumb-parent">{{ route.path.startsWith('/org') ? '组织与权限' : '知识工作区' }}</span><ChevronRight class="crumb-divider" :size="13" /><span>{{ route.meta.title }}</span></div><div class="top-actions"><RouterLink to="/profile" class="text-button"><UserRound :size="16"/><span class="desktop-label">个人中心</span></RouterLink><button class="icon-button" aria-label="退出登录" @click="logout"><LogOut :size="16"/></button></div></header>
    <main class="sheet" id="main-content"><RouterView :key="route.path" /></main>
  </div>
</template>
