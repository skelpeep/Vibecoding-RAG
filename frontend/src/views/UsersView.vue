<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { Plus, Search, RotateCw, ChevronLeft, ChevronRight, MoreHorizontal, SlidersHorizontal } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorText, flattenDepartments, formatDate, write } from '../api'
import { useAuth } from '../stores/auth'
import type { Department, Role, User } from '../types'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import FormDialog from '../components/FormDialog.vue'
import FieldInput from '../components/FieldInput.vue'
import UserAvatar from '../components/UserAvatar.vue'
import DataTable from '../components/DataTable.vue'
import FilterBar from '../components/FilterBar.vue'

const auth=useAuth(),users=ref<User[]>([]),departments=ref<Department[]>([]),roles=ref<Role[]>([])
const loading=ref(true),error=ref(''),search=ref(''),status=ref(''),department=ref(''),page=ref(1),total=ref(0),filtersOpen=ref(false),menu=ref('')
const flatDepartments=computed(()=>flattenDepartments(departments.value))
const lookupError=ref(''),lookupLoading=ref(true),rolesReady=ref(false),departmentsReady=ref(false)
async function loadLookups(){lookupLoading.value=true;lookupError.value='';const results=await Promise.allSettled([auth.has('org:department:read')?api.departments():Promise.resolve({items:[]}),auth.has('org:role:read')?api.roles():Promise.resolve({items:[]})]);departmentsReady.value=results[0].status==='fulfilled'&&auth.has('org:department:read');rolesReady.value=results[1].status==='fulfilled'&&auth.has('org:role:read');if(results[0].status==='fulfilled')departments.value=results[0].value.items;if(results[1].status==='fulfilled')roles.value=results[1].value.items;if(results.some(r=>r.status==='rejected'))lookupError.value='部门或角色选项加载失败，相关选择暂不可用。';lookupLoading.value=false}
let requestVersion=0, searchTimer:ReturnType<typeof setTimeout>
async function load() {const version=++requestVersion;loading.value=true;error.value='';try {const params:Record<string,string|number>={page:page.value,page_size:20,search:search.value};if(status.value)params.status=status.value;if(department.value)params.department_id=department.value;const r=await api.users(params);if(version===requestVersion){users.value=r.items;total.value=r.total}}catch(e){if(version===requestVersion)error.value=errorText(e)}finally{if(version===requestVersion)loading.value=false}}
watch([status,department],()=>{page.value=1;void load()})
watch(search,()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{page.value=1;void load()},250)})
onMounted(()=>{void load();void loadLookups()})
onUnmounted(()=>{clearTimeout(searchTimer);requestVersion++})
function paging(delta:number){page.value+=delta;void load()}
function canManage(){return ['org:user:assign-roles','org:user:status','org:user:reset-password'].some(auth.has)}
const dialog=ref<'create'|'edit'|'roles'|'password'|null>(null),selected=ref<User|null>(null),busy=ref(false),formError=ref('')
const form=reactive({username:'',password:'',display_name:'',email:'',department_id:'',role_ids:[] as string[]})
function open(kind:typeof dialog.value,user?:User){selected.value=user||null;menu.value='';formError.value='';Object.assign(form,{username:user?.username||'',password:'',display_name:user?.display_name||'',email:user?.email||'',department_id:user?.department_id||'',role_ids:user?.roles.map(r=>r.id)||[]});dialog.value=kind}
const dialogTitle=computed(()=>dialog.value==='create'?'新增用户':dialog.value==='edit'?'编辑用户':dialog.value==='roles'?'分配角色':'重置密码')
async function save(){busy.value=true;formError.value='';try {
  if(dialog.value==='roles'&&!rolesReady.value)throw new Error('角色选项暂不可用，请重试或联系管理员授予查看角色权限。')
  const base={display_name:form.display_name.trim(),email:form.email.trim()||null,department_id:form.department_id||null}
  if(dialog.value==='create')await write('/org/users',{...base,username:form.username.trim(),password:form.password,role_ids:auth.has('org:user:assign-roles')?form.role_ids:[]})
  else if(dialog.value==='edit')await write(`/org/users/${selected.value!.id}`,base,'PUT')
  else if(dialog.value==='roles')await write(`/org/users/${selected.value!.id}/roles`,{role_ids:form.role_ids})
  else await write(`/org/users/${selected.value!.id}/reset-password`,{password:form.password})
  dialog.value=null;form.password='';ElMessage.success('已保存');await load();await auth.refresh()
}catch(e){formError.value=errorText(e)}finally{busy.value=false}}
async function changeStatus(user:User){menu.value='';const disable=user.status==='active';try {await ElMessageBox.confirm(`${disable?'停用后该用户将无法登录，现有登录会立即失效。':'启用后该用户可以重新登录。'}`,`${disable?'停用':'启用'}「${user.display_name}」`,{confirmButtonText:disable?'确认停用':'确认启用',cancelButtonText:'取消'});await write(`/org/users/${user.id}/status`,{status:disable?'disabled':'active'});ElMessage.success(disable?'账号已停用':'账号已启用');await load();await auth.refresh()}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(errorText(e))}}
</script>
<template>
  <PageHeader title="用户管理" description="维护成员身份、部门归属与角色关联。"><button v-if="auth.has('org:user:create')" class="button primary" @click="open('create')"><Plus :size="17"/>新增用户</button></PageHeader>
  <div class="tabs" aria-label="账号状态"><button v-for="tab in [{value:'',label:'全部用户'},{value:'active',label:'启用'},{value:'disabled',label:'停用'}]" :key="tab.value" :class="{active:status===tab.value}" @click="status=tab.value">{{tab.label}}</button></div>
  <p v-if="lookupError" class="notice" role="alert">{{lookupError}} <button class="text-button" :disabled="lookupLoading" @click="loadLookups">重试选项</button></p>
  <FilterBar label="筛选用户"><div class="search-field"><Search :size="17"/><input v-model="search" aria-label="搜索用户" placeholder="搜索姓名或用户名"/></div><button class="button mobile-filter" :aria-expanded="filtersOpen" @click="filtersOpen=!filtersOpen"><SlidersHorizontal :size="16"/>筛选</button><select v-if="auth.has('org:department:read')" v-model="department" class="department-filter" :class="{'filter-open':filtersOpen}" aria-label="筛选部门" :disabled="!departmentsReady"><option value="">全部部门</option><option v-for="d in flatDepartments" :key="d.id" :value="d.id">{{'　'.repeat(d.depth)}}{{d.name}}</option></select><template #end><span class="muted num">{{loading?'加载中':`共 ${total} 位用户`}}</span><button class="icon-button" aria-label="刷新用户" :disabled="loading" @click="load"><RotateCw :size="16"/></button></template></FilterBar>
  <AsyncState :loading="loading" :error="error" :empty="!users.length" empty-text="没有找到符合条件的用户" @retry="load"><template #empty><p>试试其他姓名、部门或账号状态。</p><button v-if="search||department||status" class="text-button" @click="search='';department='';status=''">清除筛选</button></template>
    <DataTable label="组织成员" table-class="users-table"><template #head><tr><th>成员</th><th>所属部门</th><th>角色</th><th>账号状态</th><th class="num">更新时间</th><th class="actions-col">操作</th></tr></template><tr v-for="user in users" :key="user.id"><td class="identity-cell"><div class="person"><UserAvatar :name="user.display_name" :identity="user.id"/><div><strong>{{user.display_name}}</strong><small>{{user.username}}</small></div></div></td><td data-label="部门">{{user.department?.name||'—'}}</td><td data-label="角色"><div class="role-tags"><span v-for="role in user.roles" :key="role.id" class="tag">{{role.role_name}}</span><span v-if="!user.roles.length" class="muted">—</span></div></td><td class="status-cell"><span class="status" :class="user.status"><span></span>{{user.status==='active'?'启用':'停用'}}</span></td><td class="num date-cell" data-label="更新">{{formatDate(user.updated_at)}}</td><td class="row-actions"><button v-if="auth.has('org:user:update')" class="text-button" :aria-label="`编辑 ${user.username}`" @click="open('edit',user)">编辑</button><div v-if="canManage()" class="row-menu"><button class="icon-button" :aria-label="`更多操作 ${user.username}`" :aria-expanded="menu===user.id" @click="menu=menu===user.id?'':user.id"><MoreHorizontal :size="18"/></button><div v-if="menu===user.id" class="dropdown"><button v-if="auth.has('org:user:assign-roles')" :disabled="!rolesReady" :title="rolesReady?'':'需要可用的角色选项与查看角色权限'" @click="open('roles',user)">分配角色</button><button v-if="auth.has('org:user:reset-password')" @click="open('password',user)">重置密码</button><button v-if="auth.has('org:user:status')" @click="changeStatus(user)">{{user.status==='active'?'停用账号':'启用账号'}}</button><button class="muted" @click="menu=''">关闭菜单</button></div></div><span v-if="!canManage()&&!auth.has('org:user:update')" class="muted">只读</span></td></tr></DataTable>
    <div class="pagination"><span class="muted num">第 {{(page-1)*20+1}}–{{Math.min(page*20,total)}} 位，共 {{total}} 位</span><div><button class="icon-button" aria-label="上一页" :disabled="page===1" @click="paging(-1)"><ChevronLeft :size="17"/></button><span class="num">{{page}}</span><button class="icon-button" aria-label="下一页" :disabled="page*20>=total" @click="paging(1)"><ChevronRight :size="17"/></button></div></div>
  </AsyncState>
  <div class="context-note"><ShieldCheckIcon/><span>账号与角色决定可执行的操作，知识正文仍按每篇文档的访问范围授权。</span></div>
  <FormDialog :open="!!dialog" :title="dialogTitle" :busy="busy" :error="formError" @close="dialog=null;form.password=''" @submit="save">
    <p v-if="selected" class="dialog-subtitle">{{selected.display_name}} · {{selected.username}}</p>
    <template v-if="dialog==='create'||dialog==='edit'"><FieldInput v-if="dialog==='create'" v-slot="{id}" label="用户名" hint="小写字母、数字、下划线、短横线或点，创建后不可修改。" required><input :id="id" v-model="form.username" required maxlength="64" pattern="[a-z0-9][a-z0-9_.-]*" autocomplete="off"/></FieldInput><FieldInput v-slot="{id}" label="显示名称" required><input :id="id" v-model="form.display_name" required maxlength="100"/></FieldInput><FieldInput v-slot="{id}" label="邮箱"><input :id="id" v-model="form.email" type="email" maxlength="254"/></FieldInput><FieldInput v-slot="{id}" label="所属部门"><select :id="id" v-model="form.department_id" :disabled="!departmentsReady"><option value="">未分配部门</option><option v-for="d in flatDepartments" :key="d.id" :value="d.id">{{'　'.repeat(d.depth)}}{{d.name}}</option><option v-if="selected?.department&&!flatDepartments.some(d=>d.id===selected?.department_id)" :value="selected.department_id||''">{{selected.department.name}}</option></select></FieldInput></template>
    <FieldInput v-if="dialog==='create'||dialog==='password'" v-slot="{id}" :label="dialog==='create'?'初始密码':'新密码'" hint="至少 12 位，最多 128 位；请通过安全渠道告知本人。" required><input :id="id" v-model="form.password" type="password" required minlength="12" maxlength="128" autocomplete="new-password"/></FieldInput>
    <div v-if="dialog==='roles'||(dialog==='create'&&auth.has('org:user:assign-roles')&&rolesReady)" class="field"><label>关联角色</label><div class="choice-list"><label v-for="role in roles" :key="role.id" class="checkbox-row"><input v-model="form.role_ids" type="checkbox" :disabled="!rolesReady" :value="role.id"/><span>{{role.role_name}}<small>{{role.role_code}}</small></span></label><p v-if="!roles.length" class="muted">暂无可选择角色，需具备查看角色权限。</p></div></div>
    <p v-if="dialog==='password'" class="notice">重置后，该账号的全部现有登录将失效。</p>
  </FormDialog>
</template>
<script lang="ts">
import { ShieldCheck as ShieldCheckIcon } from 'lucide-vue-next'
export default {components:{ShieldCheckIcon}}
</script>
