<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Plus, ChevronRight, ArrowLeft, ShieldCheck, Pencil, Trash2 } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api, errorText, TOKEN_KEY, write } from '../api'
import { useAuth } from '../stores/auth'
import type { Permission, Role } from '../types'
import PageHeader from '../components/PageHeader.vue'
import MasterDetail from '../components/MasterDetail.vue'
import AsyncState from '../components/AsyncState.vue'
import PermissionPicker from '../components/PermissionPicker.vue'
import FormDialog from '../components/FormDialog.vue'
import FieldInput from '../components/FieldInput.vue'
const auth=useAuth(),roles=ref<Role[]>([]),catalog=ref<Permission[]>([]),selectedId=ref(''),selected=computed(()=>roles.value.find(r=>r.id===selectedId.value))
const loading=ref(true),error=ref(''),codes=ref<string[]>([]),saving=ref(false),saveError=ref(''),mobileDetail=ref(false)
const dirty=computed(()=>JSON.stringify([...codes.value].sort())!==JSON.stringify([...(selected.value?.permission_codes||[])].sort()))
onBeforeRouteLeave(async()=>{if(!dirty.value||!sessionStorage.getItem(TOKEN_KEY))return true;try{await ElMessageBox.confirm('当前权限修改尚未保存，离开后将丢弃这些修改。','离开权限配置',{confirmButtonText:'丢弃并离开',cancelButtonText:'继续编辑'});return true}catch{return false}})
function warnUnsaved(event:BeforeUnloadEvent){if(dirty.value){event.preventDefault();event.returnValue=''}}
onMounted(()=>window.addEventListener('beforeunload',warnUnsaved))
onUnmounted(()=>window.removeEventListener('beforeunload',warnUnsaved))
async function load(){loading.value=true;error.value='';try{const [r,p]=await Promise.all([api.roles(),api.permissions()]);roles.value=r.items;catalog.value=p.items;selectedId.value=roles.value.some(r=>r.id===selectedId.value)?selectedId.value:roles.value[0]?.id||'';codes.value=[...(selected.value?.permission_codes||[])]}catch(e){error.value=errorText(e)}finally{loading.value=false}}
onMounted(load)
async function choose(role:Role){if(dirty.value){try{await ElMessageBox.confirm('当前权限修改尚未保存，切换后将丢弃这些修改。','切换角色',{confirmButtonText:'丢弃并切换',cancelButtonText:'继续编辑'})}catch{return}}selectedId.value=role.id;codes.value=[...(role.permission_codes||[])];saveError.value='';mobileDetail.value=true}
async function savePermissions(){if(!selected.value)return;saving.value=true;saveError.value='';try{await ElMessageBox.confirm(`将为「${selected.value.role_name}」保存 ${codes.value.length} 项菜单与操作权限，相关成员的后续请求立即生效。`,'保存角色权限',{confirmButtonText:'确认保存',cancelButtonText:'取消'});const role=await write<Role>(`/org/roles/${selectedId.value}/permissions`,{permission_codes:codes.value});Object.assign(selected.value,role);ElMessage.success('角色权限已保存');await auth.refresh()}catch(e){if(e!=='cancel'&&e!=='close')saveError.value=errorText(e)}finally{saving.value=false}}
const dialog=ref(false),editing=ref<Role|null>(null),busy=ref(false),formError=ref(''),form=reactive({role_name:'',role_code:'',description:''})
function open(role?:Role){editing.value=role||null;Object.assign(form,{role_name:role?.role_name||'',role_code:role?.role_code||'',description:role?.description||''});formError.value='';dialog.value=true}
async function save(){busy.value=true;formError.value='';try{const r=await write<Role>(editing.value?`/org/roles/${editing.value.id}`:'/org/roles',form,editing.value?'PUT':'POST');selectedId.value=r.id;dialog.value=false;await load();ElMessage.success('角色已保存')}catch(e){formError.value=errorText(e)}finally{busy.value=false}}
async function remove(){if(!selected.value)return;try{await ElMessageBox.confirm('删除后无法恢复；仍有关联成员或知识授权的角色不能删除。',`删除「${selected.value.role_name}」`,{confirmButtonText:'确认删除',cancelButtonText:'取消'});await write(`/org/roles/${selectedId.value}`,undefined,'DELETE');selectedId.value='';await load();ElMessage.success('角色已删除')}catch(e){if(e!=='cancel'&&e!=='close')ElMessage.error(errorText(e))}}
</script>
<template>
  <PageHeader title="角色与权限" description="把职责定义为角色，按需授予菜单与操作。"><button v-if="auth.has('org:role:create')" class="button" @click="open()"><Plus :size="17"/>新增角色</button></PageHeader>
  <AsyncState :loading="loading" :error="error" :empty="!roles.length" empty-text="尚未创建角色" @retry="load">
    <MasterDetail :show-detail="mobileDetail"><template #master><div class="section-label"><span>组织角色</span><span class="num">{{roles.length}}</span></div><button v-for="role in roles" :key="role.id" class="object-row" :class="{selected:role.id===selectedId}" @click="choose(role)"><div><strong>{{role.role_name}}</strong><small>{{role.role_code}}</small></div><span class="object-meta num">{{role.permission_codes?.length||0}} 项</span><ChevronRight :size="15"/></button><p class="pane-note">同一成员可关联多个角色，其操作权限合并生效。</p></template>
    <template v-if="selected"><button class="text-button mobile-back" @click="mobileDetail=false"><ArrowLeft :size="16"/>返回角色列表</button><div class="detail-head"><div><h2>{{selected.role_name}}</h2><p class="muted">{{selected.description||'尚未填写角色说明'}}</p></div><div class="detail-actions"><button v-if="auth.has('org:role:update')" class="icon-button" aria-label="编辑角色" @click="open(selected)"><Pencil :size="16"/></button><button v-if="auth.has('org:role:delete')" class="icon-button" aria-label="删除角色" @click="remove"><Trash2 :size="16"/></button></div></div><div class="permission-summary"><ShieldCheck :size="19"/><div><strong>已选择 <span class="num">{{codes.length}}</span> 项权限</strong><p>菜单控制入口，操作控制行为。知识正文另行授权。</p></div><span v-if="dirty" class="unsaved">有未保存修改</span></div><PermissionPicker v-model="codes" :items="catalog" :disabled="!auth.has('org:role:permissions')||saving"/><p v-if="saveError" class="form-error" role="alert">{{saveError}}</p><div class="save-bar"><span class="muted">{{auth.has('org:role:permissions')?'保存后立即影响角色成员的后续操作。':'你可以查看当前角色权限。'}}</span><button v-if="auth.has('org:role:permissions')" class="button primary" :disabled="!dirty||saving" @click="savePermissions">{{saving?'保存中…':'保存权限'}}</button></div></template></MasterDetail>
  </AsyncState>
  <FormDialog :open="dialog" :title="editing?'编辑角色':'新增角色'" :busy="busy" :error="formError" @close="dialog=false" @submit="save"><FieldInput v-slot="{id}" label="角色名称" required><input :id="id" v-model="form.role_name" required maxlength="100"/></FieldInput><FieldInput v-slot="{id}" label="角色编码" hint="小写字母、数字、下划线、短横线或点。" required><input :id="id" v-model="form.role_code" required pattern="[a-z0-9][a-z0-9_.-]*" maxlength="64"/></FieldInput><FieldInput v-slot="{id}" label="角色说明"><textarea :id="id" v-model="form.description" rows="3" maxlength="500"/></FieldInput></FormDialog>
</template>
