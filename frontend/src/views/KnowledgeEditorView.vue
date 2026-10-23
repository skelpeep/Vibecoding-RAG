<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { errorText, ApiError, write } from '../api'
import { knowledge, type Grant, type GrantOptions, type UnitDetail } from '../knowledge'
import { useAuth } from '../stores/auth'
import { useUnsaved } from '../useUnsaved'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import FieldInput from '../components/FieldInput.vue'
import KnowledgeGrantPicker from '../components/KnowledgeGrantPicker.vue'
const route=useRoute(),router=useRouter(),auth=useAuth(),editing=computed(()=>!!route.params.id)
const form=reactive({title:'',content:'',summary:'',category:'',tags:''}),grants=ref<Grant[]>([]),options=ref<GrantOptions>({departments:[],roles:[],users:[]}),grantError=ref(''),optionsReady=ref(false)
const loading=ref(true),error=ref(''),formError=ref(''),busy=ref(false),unit=ref<UnitDetail|null>(null),baseline=ref(''),saved=ref(false)
const snapshot=()=>JSON.stringify({form,grants:grants.value})
const dirty=computed(()=>!saved.value&&baseline.value!==''&&snapshot()!==baseline.value)
useUnsaved(()=>dirty.value,()=>busy.value)
let alive=true
async function load(){loading.value=true;error.value='';try{if(editing.value){const result=await knowledge.detail(String(route.params.id));if(!alive)return;if(!result.can_edit||!auth.has('knowledge:update'))throw new Error('你没有维护这篇知识的权限。');unit.value=result;Object.assign(form,{title:result.title,content:result.content||'',summary:result.summary||'',category:result.category||'',tags:(result.tags||[]).join('，')})}baseline.value=snapshot()}catch(e){unit.value=null;Object.assign(form,{title:'',content:'',summary:'',category:'',tags:''});error.value=errorText(e)}finally{loading.value=false}}
async function loadOptions(){grantError.value='';try{options.value=await knowledge.options();optionsReady.value=true}catch(e){grantError.value=errorText(e);optionsReady.value=false}}
async function save(){if(busy.value)return;formError.value='';if(!form.title.trim()||!form.content.trim()){formError.value='请填写标题与正文。';return}const tags=[...new Set(form.tags.split(/[,，\n]/).map(x=>x.trim()).filter(Boolean))];if(tags.length>30||tags.some(x=>x.length>50)){formError.value='最多 30 个标签，每个不超过 50 字。';return}if(form.content.length>2000000){formError.value='正文超过支持长度，请拆分为多篇知识。';return}busy.value=true;try{const payload={title:form.title.trim(),content:form.content,summary:form.summary.trim(),category:form.category.trim(),tags,...(!editing.value&&auth.has('knowledge:permissions')?{grants:grants.value}:{})};const result=editing.value?await knowledge.update(String(route.params.id),payload):route.query.gap?(await write<{unit:UnitDetail}>(`/settlement/knowledge-gaps/${String(route.query.gap)}/draft`,payload)).unit:await knowledge.create(payload);saved.value=true;busy.value=false;ElMessage.success('已保存，正在构建新版本');await router.push(`/knowledge/${result.id}`)}catch(e){formError.value=errorText(e);if(e instanceof ApiError&&[403,404].includes(e.status)){saved.value=true;Object.assign(form,{title:'',content:'',summary:'',category:'',tags:''});unit.value=null;error.value='权限已变化，文档内容已清除。'}}finally{busy.value=false}}
async function verifyAccess(){if(!editing.value||document.visibilityState!=='visible')return;try{const r=await knowledge.detail(String(route.params.id));if(!r.can_edit)throw new ApiError(403,'维护权限已撤销')}catch(e){if(e instanceof ApiError&&[401,403,404].includes(e.status)){saved.value=true;Object.assign(form,{title:'',content:'',summary:'',category:'',tags:''});grants.value=[];unit.value=null;error.value='已无权维护这篇知识，内容已清除。'}}}
let interval:ReturnType<typeof setInterval>
onMounted(()=>{if(!editing.value&&route.query.title)form.title=String(route.query.title).slice(0,255);void load();if(!editing.value&&auth.has('knowledge:permissions'))void loadOptions();interval=setInterval(verifyAccess,30000);window.addEventListener('focus',verifyAccess)})
watch(()=>auth.permissions.join('|'),()=>{if((editing.value&&!auth.has('knowledge:update'))||(!editing.value&&!auth.has('knowledge:create'))){saved.value=true;Object.assign(form,{title:'',content:'',summary:'',category:'',tags:''});grants.value=[];error.value='操作权限已变化，未保存内容已清除。'}})
onUnmounted(()=>{alive=false;clearInterval(interval);window.removeEventListener('focus',verifyAccess)})
</script>
<template>
 <div class="knowledge-screen">
 <RouterLink :to="editing?`/knowledge/${route.params.id}`:'/knowledge'" class="text-button back-link"><ArrowLeft :size="16"/>{{editing?'返回知识详情':'返回知识列表'}}</RouterLink>
 <PageHeader :title="editing?'编辑知识':'新建知识'" description="保存后生成新版本；构建就绪后，可在详情中激活并发布。"><button class="button primary" form="knowledge-editor" :disabled="loading||busy||!!error">{{busy?'保存中…':'保存知识'}}</button></PageHeader>
 <AsyncState :loading="loading" :error="error" @retry="load">
 <form id="knowledge-editor" class="knowledge-editor-grid" @submit.prevent="save">
  <section class="editor-main" aria-label="知识内容"><FieldInput v-slot="{id}" label="标题" required><input :id="id" v-model="form.title" required maxlength="255" :disabled="busy" placeholder="为这篇知识填写清楚的标题"/></FieldInput><FieldInput v-slot="{id}" label="正文" hint="支持保留 Markdown 文本。正文和版本历史可在详情中查看。" required><textarea :id="id" v-model="form.content" class="content-editor" required :disabled="busy" placeholder="填写可复用的知识、操作说明或常见处理方法…"/></FieldInput><div class="editor-bottom"><span class="muted num">{{form.content.length.toLocaleString()}} 字符</span><span v-if="dirty" class="muted">有未保存的修改</span></div><p v-if="formError" class="form-error" role="alert">{{formError}}</p></section>
  <aside class="editor-aside"><h2>文档资料</h2><FieldInput v-slot="{id}" label="分类"><input :id="id" v-model="form.category" maxlength="100" :disabled="busy" placeholder="如：产品文档、工作流程"/></FieldInput><FieldInput v-slot="{id}" label="标签" hint="用逗号分隔，最多 30 个，每个不超过 50 字。"><input :id="id" v-model="form.tags" maxlength="1000" :disabled="busy" placeholder="如：入门，故障处理"/></FieldInput><FieldInput v-slot="{id}" label="摘要"><textarea :id="id" v-model="form.summary" rows="4" maxlength="2000" :disabled="busy" placeholder="概括适用场景和主要内容"/></FieldInput><div class="editor-version-note"><h3>{{editing?'版本维护':'首次发布'}}</h3><p>{{editing?'保存不会切换当前发布版本。新版本构建失败时，原有可用版本保持不变。':'新知识以草稿保存。完成构建、配置访问范围并激活版本后，再发布给读者。'}}</p><p>附件可在保存后的知识详情中添加。</p></div></aside>
  <section v-if="!editing&&auth.has('knowledge:permissions')" class="create-grants"><h2>初始访问范围</h2><p class="muted">默认不开放，可在发布前继续调整。</p><div v-if="grantError" class="notice" role="alert">{{grantError}} <button type="button" class="text-button" @click="loadOptions">重新加载</button></div><KnowledgeGrantPicker v-if="optionsReady" v-model="grants" :options="options" :disabled="busy"/></section>
 </form>
 </AsyncState>
 </div>
</template>
