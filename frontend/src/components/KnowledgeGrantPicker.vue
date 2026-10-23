<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { knowledge, type Grant, type GrantOptions } from '../knowledge'
const props=defineProps<{modelValue:Grant[];options:GrantOptions;disabled?:boolean}>()
const emit=defineEmits<{'update:modelValue':[Grant[]]}>()
const search=ref(''),extraUsers=ref<GrantOptions['users']>([]),searching=ref(false),searchError=ref('')
let timer:ReturnType<typeof setTimeout>,sequence=0
watch(search,()=>{clearTimeout(timer);const v=++sequence;searchError.value='';if(!search.value.trim())return;timer=setTimeout(async()=>{searching.value=true;try{const result=await knowledge.options(search.value.trim());if(v===sequence)extraUsers.value=[...new Map([...extraUsers.value,...result.users].map(user=>[user.id,user])).values()]}catch{if(v===sequence)searchError.value='成员查找暂不可用，请稍后再试。'}finally{if(v===sequence)searching.value=false}},300)})
onUnmounted(()=>{clearTimeout(timer);sequence++})
const groups=computed(()=>[
 {type:'department' as const,label:'部门',note:'仅直属部门，不含下级部门',items:props.options.departments.map(x=>({id:x.id,label:x.name,sub:''}))},
 {type:'role' as const,label:'角色',note:'拥有任一所选角色的成员',items:props.options.roles.map(x=>({id:x.id,label:x.role_name,sub:''}))},
 {type:'user' as const,label:'个人',note:'仅指定成员本人；输入姓名可查找更多成员',items:[...new Map([...props.options.users,...extraUsers.value].map(x=>[x.id,x])).values()].map(x=>({id:x.id,label:x.display_name,sub:x.username}))},
])
function selected(type:Grant['target_type'],id:string){return props.modelValue.some(g=>g.target_type===type&&g.target_id===id)}
function toggle(type:Grant['target_type'],id:string){if(props.disabled)return;emit('update:modelValue',selected(type,id)?props.modelValue.filter(g=>!(g.target_type===type&&g.target_id===id)):[...props.modelValue,{target_type:type,target_id:id}])}
function filtered(items:{id:string;label:string;sub:string}[]){const q=search.value.trim().toLocaleLowerCase();return items.filter(x=>`${x.label} ${x.sub}`.toLocaleLowerCase().includes(q))}
const unknown=computed(()=>props.modelValue.filter(g=>g.target_type!=='global'&&!groups.value.find(group=>group.type===g.target_type)?.items.some(x=>x.id===g.target_id)))
</script>
<template>
 <div class="grant-picker">
  <p class="grant-explanation">满足任意一项即可阅读已发布知识。未选择时，任何读者均不可访问。</p>
  <label class="checkbox-row global-choice"><input type="checkbox" :checked="selected('global','*')" :disabled="disabled" @change="toggle('global','*')"/><span>全局开放<small>组织内所有具备知识阅读权限的账号</small></span></label>
  <input v-model="search" class="grant-search" aria-label="查找授权对象" placeholder="查找部门、角色或成员" :disabled="disabled"/>
  <p v-if="searching" class="muted grant-note" role="status">正在查找成员…</p><p v-if="searchError" class="form-error" role="alert">{{searchError}}</p>
  <details v-for="group in groups" :key="group.type" class="grant-group" :open="group.type==='department'||!!search">
   <summary><strong>{{group.label}}</strong><span class="muted">{{modelValue.filter(x=>x.target_type===group.type).length}} 项已选</span></summary>
   <p class="muted grant-note">{{group.note}}</p>
   <div class="grant-choices"><label v-for="item in filtered(group.items)" :key="item.id" class="checkbox-row"><input type="checkbox" :checked="selected(group.type,item.id)" :disabled="disabled" @change="toggle(group.type,item.id)"/><span>{{item.label}}<small v-if="item.sub">{{item.sub}}</small></span></label><p v-if="!filtered(group.items).length" class="muted">没有匹配的{{group.label}}。</p></div>
  </details>
  <div v-if="unknown.length" class="notice">另有 {{unknown.length}} 项现有授权对象未出现在可选列表中，将保留原配置。<button v-for="grant in unknown" :key="grant.target_id" type="button" class="text-button" :disabled="disabled" @click="toggle(grant.target_type,grant.target_id)">移除 {{grant.target_type}} {{grant.target_id.slice(0,8)}}</button></div>
  <p class="grant-result">{{selected('global','*')?'已选择全局开放':modelValue.length?`已选 ${modelValue.length} 项授权，按任一匹配生效`:'默认关闭 · 尚未开放阅读'}}</p>
 </div>
</template>
