<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ArrowRight, ShieldCheck, Network } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'
import { errorText, write } from '../api'
import PageHeader from '../components/PageHeader.vue'
import FieldInput from '../components/FieldInput.vue'
import UserAvatar from '../components/UserAvatar.vue'
const auth=useAuth(),router=useRouter(),form=reactive({display_name:'',email:''}),password=reactive({current_password:'',new_password:'',confirm:''})
const saving=ref(false),changing=ref(false),error=ref(''),passwordError=ref('')
watch(()=>auth.user,(user,previous)=>{if(user&&(!previous||user.id!==previous.id||(form.display_name===previous.display_name&&form.email===(previous.email||'')))){form.display_name=user.display_name;form.email=user.email||''}},{immediate:true})
const dirty=computed(()=>form.display_name!==auth.user?.display_name||form.email!==(auth.user?.email||''))
async function save(){saving.value=true;error.value='';try{await write('/auth/profile',{display_name:form.display_name,email:form.email||null},'PUT');await auth.refresh();ElMessage.success('个人资料已更新')}catch(e){error.value=errorText(e)}finally{saving.value=false}}
async function changePassword(){if(password.new_password!==password.confirm){passwordError.value='两次输入的新密码不一致。';return}changing.value=true;passwordError.value='';try{await write('/auth/password',{current_password:password.current_password,new_password:password.new_password});auth.clear();await router.replace({path:'/login',query:{expired:'1'}});ElMessage.success('密码已更新，请重新登录')}catch(e){passwordError.value=errorText(e)}finally{changing.value=false}}
</script>
<template>
  <PageHeader title="个人中心" description="查看当前身份，维护个人资料与账号安全。"/>
  <div v-if="auth.user" class="identity-strip"><div class="identity-node person"><UserAvatar :name="auth.user.display_name" :identity="auth.user.id"/><div><strong>{{auth.user.display_name}}</strong><small>{{auth.user.username}}</small></div></div><ArrowRight :size="16" class="identity-arrow"/><div class="identity-node"><Network :size="18"/><div><small>直属部门</small><strong>{{auth.user.department?.name||'未分配部门'}}</strong></div></div><ArrowRight :size="16" class="identity-arrow"/><div class="identity-node"><ShieldCheck :size="18"/><div><small>关联角色</small><strong>{{auth.user.roles.map(r=>r.role_name).join('、')||'未分配角色'}}</strong></div></div><div class="identity-count"><strong class="num">{{auth.permissions.filter(p=>!p.startsWith('menu:')).length}}</strong><span>项操作权限</span></div></div>
  <section class="settings-section"><div class="settings-label"><h2>个人资料</h2><p>显示名称用于组织成员列表。用户名由管理员创建，无法自行修改。</p><dl class="small-facts"><dt>用户名</dt><dd>{{auth.user?.username}}</dd><dt>账号状态</dt><dd>启用</dd></dl></div><form class="settings-form" @submit.prevent="save"><FieldInput v-slot="{id}" label="显示名称" required><input :id="id" v-model="form.display_name" required maxlength="100"/></FieldInput><FieldInput v-slot="{id}" label="邮箱"><input :id="id" v-model="form.email" type="email" maxlength="254" placeholder="用于组织内联系"/></FieldInput><p v-if="error" class="form-error" role="alert">{{error}}</p><div class="form-actions"><button class="button primary" :disabled="saving||!dirty">{{saving?'保存中…':'保存资料'}}</button></div></form></section>
  <section class="settings-section"><div class="settings-label"><h2>账号安全</h2><p>定期更新密码。修改成功后，该账号在所有设备上的登录都会失效。</p></div><form class="settings-form" @submit.prevent="changePassword"><FieldInput v-slot="{id}" label="当前密码" required><input :id="id" v-model="password.current_password" type="password" required autocomplete="current-password" maxlength="128"/></FieldInput><FieldInput v-slot="{id}" label="新密码" hint="至少 12 位，最多 128 位。" required><input :id="id" v-model="password.new_password" type="password" required minlength="12" maxlength="128" autocomplete="new-password"/></FieldInput><FieldInput v-slot="{id}" label="确认新密码" required><input :id="id" v-model="password.confirm" type="password" required minlength="12" maxlength="128" autocomplete="new-password"/></FieldInput><p v-if="passwordError" class="form-error" role="alert">{{passwordError}}</p><div class="form-actions"><button class="button" :disabled="changing">{{changing?'更新中…':'更新密码'}}</button></div></form></section>
</template>
