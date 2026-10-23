import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from './stores/auth'
import { ApiError, TOKEN_KEY } from './api'
import AppLayout from './components/AppLayout.vue'

export const router = createRouter({history: createWebHistory(), routes: [
  {path: '/login', component: () => import('./views/LoginView.vue'), meta: {title: '登录', public: true}},
  {path: '/', component: AppLayout, children: [
    {path: '', redirect: () => useAuth().home()},
    {path: 'org/users', component: () => import('./views/UsersView.vue'), meta: {title: '用户管理', menu: 'menu:org', permission: 'org:user:read'}},
    {path: 'org/roles', component: () => import('./views/RolesView.vue'), meta: {title: '角色与权限', menu: 'menu:org', permission: 'org:role:read'}},
    {path: 'org/departments', component: () => import('./views/DepartmentsView.vue'), meta: {title: '部门管理', menu: 'menu:org', permission: 'org:department:read'}},
    {path: 'profile', component: () => import('./views/ProfileView.vue'), meta: {title: '个人中心'}},
    {path:'knowledge',component:()=>import('./views/KnowledgeListView.vue'),meta:{title:'知识维护',menu:'menu:knowledge'}},
    {path:'knowledge/new',component:()=>import('./views/KnowledgeEditorView.vue'),meta:{title:'新建知识',menu:'menu:knowledge',permission:'knowledge:create'}},
    {path:'knowledge/import',component:()=>import('./views/KnowledgeImportView.vue'),meta:{title:'导入中心',menu:'menu:knowledge'}},
    {path:'knowledge/:id/edit',component:()=>import('./views/KnowledgeEditorView.vue'),meta:{title:'编辑知识',menu:'menu:knowledge',permission:'knowledge:update'}},
    {path:'knowledge/:id',component:()=>import('./views/KnowledgeDetailView.vue'),meta:{title:'知识详情',menu:'menu:knowledge'}},
    {path:'chat',component:()=>import('./views/ChatView.vue'),meta:{title:'AI 问答',menu:'menu:ai',permission:'ai:chat'}},
    {path:'dashboard',component:()=>import('./views/DashboardView.vue'),meta:{title:'数据看板',menu:'menu:dashboard',permission:'dashboard:read'}},
    {path:'settlement',component:()=>import('./views/SettlementView.vue'),meta:{title:'知识沉淀',menu:'menu:settlement'}},
    {path: 'forbidden', component: () => import('./views/StatusView.vue'), meta: {title: '访问受限'}},
    {path: 'unavailable', component: () => import('./views/StatusView.vue'), meta: {title: '连接暂时不可用'}},
    {path: ':pathMatch(.*)*', component: () => import('./views/StatusView.vue'), meta: {title: '页面不存在'}},
  ]},
]})
router.beforeEach(async to => {
  document.title = `${String(to.meta.title || '工作区')} · 知识库管理平台`
  if (to.meta.public) return true
  if (!sessionStorage.getItem(TOKEN_KEY)) return {path:'/login',query:{redirect:to.fullPath}}
  const auth = useAuth()
  if (to.path !== '/unavailable') {
    try { await auth.refresh() } catch(error) { if (error instanceof ApiError && error.status === 401) return {path:'/login',query:{expired:'1'}}; return {path:'/unavailable',query:{redirect:to.fullPath}} }
  }
  if ((to.meta.menu && !auth.has(String(to.meta.menu))) || (to.meta.permission && !auth.has(String(to.meta.permission)))) return '/forbidden'
})
