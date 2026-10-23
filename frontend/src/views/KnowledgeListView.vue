<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Plus, Search, RotateCw, ChevronLeft, ChevronRight, SlidersHorizontal, Upload, Trash2 } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError, errorText, formatDate } from '../api'
import { knowledge, unitStatus, grantSummary, type Unit } from '../knowledge'
import { useAuth } from '../stores/auth'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import DataTable from '../components/DataTable.vue'
const auth=useAuth(),items=ref<Unit[]>([]),loading=ref(true),error=ref(''),search=ref(''),status=ref(''),category=ref(''),categories=ref<string[]>([]),page=ref(1),total=ref(0),filters=ref(false),selected=ref<string[]>([]),busy=ref(false)
const canDelete=computed(()=>auth.has('knowledge:delete'))
const canImport=computed(()=>auth.has('knowledge:import')||auth.has('knowledge:task:read')||auth.has('knowledge:task:read-any'))
const selectable=computed(()=>items.value.filter(x=>x.can_delete&&canDelete.value))
const allSelected=computed(()=>selectable.value.length>0&&selectable.value.every(x=>selected.value.includes(x.id)))
let version=0,timer:ReturnType<typeof setTimeout>,refreshTimer:ReturnType<typeof setInterval>
async function load(){const v=++version;loading.value=true;error.value='';selected.value=[];try{const r=await knowledge.list({page:page.value,page_size:20,search:search.value,status:status.value,category:category.value});if(v!==version)return;items.value=r.items;total.value=r.total;if(page.value>1&&!r.items.length&&r.total){page.value=Math.ceil(r.total/20);await load()}}catch(e){if(v===version){items.value=[];total.value=0;error.value=errorText(e)}}finally{if(v===version)loading.value=false}}
async function loadCategories(){try{categories.value=(await knowledge.categories()).items}catch{categories.value=[]}}
function refresh(){if(document.visibilityState==='visible'){void load();void loadCategories()}}
watch([status,category],()=>{page.value=1;void load()});watch(search,()=>{clearTimeout(timer);timer=setTimeout(()=>{page.value=1;void load()},300)})
watch(()=>auth.permissions.join('|'),()=>{selected.value=[];items.value=[];void load()})
onMounted(()=>{void load();void loadCategories();refreshTimer=setInterval(refresh,60000);window.addEventListener('focus',refresh)})
onUnmounted(()=>{version++;clearTimeout(timer);clearInterval(refreshTimer);window.removeEventListener('focus',refresh)})
function toggleAll(){selected.value=allSelected.value?[]:selectable.value.map(x=>x.id)}
function paging(delta:number){page.value+=delta;void load()}
async function remove(){try{await ElMessageBox.confirm(`确认删除所选 ${selected.value.length} 篇知识？删除后立即停止阅读、下载与检索。`,'批量删除知识',{confirmButtonText:'确认删除',cancelButtonText:'取消'});busy.value=true;await knowledge.remove(selected.value);ElMessage.success('所选知识已删除');await load();await loadCategories()}catch(e){if(e!=='cancel'&&e!=='close'){ElMessage.error(errorText(e));if(e instanceof ApiError&&[403,404].includes(e.status))await load()}}finally{busy.value=false}}
</script>
<template>
 <div class="knowledge-screen">
 <PageHeader title="知识维护" description="阅读已授权知识，维护自己创建的文档与版本。"><RouterLink v-if="canImport" to="/knowledge/import" class="button secondary-action"><Upload :size="16"/>导入中心</RouterLink><RouterLink v-if="auth.has('knowledge:create')" to="/knowledge/new" class="button primary"><Plus :size="17"/>新建知识</RouterLink></PageHeader>
 <div class="tabs" aria-label="知识发布状态"><button v-for="tab in [{value:'',label:'全部知识'},{value:'published',label:'已发布'},{value:'draft',label:'草稿'},{value:'disabled',label:'已停用'}]" :key="tab.value" :class="{active:status===tab.value}" :aria-pressed="status===tab.value" @click="status=tab.value">{{tab.label}}</button></div>
 <div class="toolbar knowledge-toolbar"><div class="search-field"><Search :size="17"/><input v-model="search" aria-label="搜索知识" placeholder="搜索标题或知识编号" maxlength="200"/></div><button class="button mobile-filter" :aria-expanded="filters" @click="filters=!filters"><SlidersHorizontal :size="16"/>筛选</button><select v-model="category" class="department-filter" :class="{'filter-open':filters}" aria-label="筛选分类"><option value="">全部分类</option><option v-for="c in categories" :key="c" :value="c">{{c}}</option></select><div class="toolbar-end"><span class="muted num">{{loading?'加载中':`共 ${total} 篇知识`}}</span><RouterLink v-if="canImport" class="text-button mobile-import" to="/knowledge/import">导入中心</RouterLink><button class="icon-button" aria-label="刷新知识" :disabled="loading" @click="refresh"><RotateCw :size="16"/></button></div></div>
 <div v-if="selected.length" class="bulk-bar"><span>已选 {{selected.length}} 篇</span><button class="text-button danger-text" :disabled="busy" @click="remove"><Trash2 :size="15"/>删除所选</button><button class="text-button" :disabled="busy" @click="selected=[]">取消选择</button></div>
 <AsyncState :loading="loading" :error="error" :empty="!items.length" empty-text="当前范围内没有知识" @retry="load"><template #empty><p>{{search||category||status?'试试其他关键词或筛选条件。':'你可以新建知识，或等待文档向你开放阅读。'}}</p><button v-if="search||category||status" class="text-button" @click="search='';category='';status=''">清除筛选</button></template>
  <DataTable label="知识列表" table-class="knowledge-table"><template #head><tr><th v-if="canDelete" class="check-cell"><input type="checkbox" aria-label="选择本页可删除知识" :checked="allSelected" :indeterminate="selected.length>0&&!allSelected" :disabled="!selectable.length||busy" @change="toggleAll"/></th><th class="knowledge-name">知识</th><th class="knowledge-category">分类</th><th class="knowledge-state">状态</th><th class="knowledge-owner">创建者</th><th class="num knowledge-date">更新时间</th><th class="knowledge-action">操作</th></tr></template>
   <tr v-for="unit in items" :key="unit.id" :class="{'has-selection':canDelete}"><td v-if="canDelete" class="check-cell"><input v-model="selected" type="checkbox" :value="unit.id" :aria-label="`选择 ${unit.title}`" :disabled="!unit.can_delete||busy"/></td><td class="identity-cell"><RouterLink :to="`/knowledge/${unit.id}`" class="knowledge-title">{{unit.title}}</RouterLink><div class="knowledge-reference"><span>{{unit.unit_code}}</span><span>{{unit.file_type?.replace('.','').toUpperCase()||'手动编写'}}</span></div><div class="knowledge-subline"><span v-if="unit.tags?.length">{{unit.tags.slice(0,3).join(' · ')}}</span><span v-else>{{unit.summary||unit.source_file_name||'—'}}</span></div><div class="knowledge-access">{{grantSummary(unit.permission_summary)}}</div></td><td class="knowledge-category" data-label="分类">{{unit.category||'未分类'}}</td><td class="status-cell"><span class="status" :class="{active:unit.status==='published'}"><span></span>{{unitStatus[unit.status]||unit.status}}</span></td><td class="knowledge-owner" data-label="创建者">{{unit.creator_name||'—'}}</td><td class="num date-cell">{{formatDate(unit.updated_at)}}</td><td class="row-actions"><RouterLink v-if="unit.can_edit&&auth.has('knowledge:update')" :to="`/knowledge/${unit.id}/edit`" class="text-button">编辑</RouterLink><RouterLink v-else :to="`/knowledge/${unit.id}`" class="text-button">查看</RouterLink></td></tr>
  </DataTable>
  <div class="pagination"><span class="muted num">第 {{(page-1)*20+1}}–{{Math.min(page*20,total)}} 篇，共 {{total}} 篇</span><div><button class="icon-button" aria-label="上一页" :disabled="page===1||loading" @click="paging(-1)"><ChevronLeft :size="17"/></button><span class="num">{{page}}</span><button class="icon-button" aria-label="下一页" :disabled="page*20>=total||loading" @click="paging(1)"><ChevronRight :size="17"/></button></div></div>
 </AsyncState>
 <p class="knowledge-footnote">草稿仅在创建者的维护范围内显示；已发布知识仍需匹配文档的访问授权。</p>
 </div>
</template>
