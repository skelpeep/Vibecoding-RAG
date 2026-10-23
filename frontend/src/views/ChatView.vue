<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ArrowDown, ArrowLeft, ArrowUp, BookOpen, MessageSquare, Plus, RefreshCw, Square, Trash2 } from 'lucide-vue-next'
import { ApiError, errorText, write } from '../api'
import { useAuth } from '../stores/auth'
import { chatApi, chatTime, safeExternalSources, sourcePosition, streamChat, type ChatEvent, type ChatSession, type ChatSource, type ChatTurn } from '../chat'
import ChatMarkdown from '../components/ChatMarkdown.vue'
import ChatCitationDialog from '../components/ChatCitationDialog.vue'
import '../chat.css'
const auth=useAuth(),route=useRoute(),router=useRouter(),verifying=ref(false)
const sessions=ref<ChatSession[]>([]),total=ref(0),page=ref(1),listLoading=ref(false),listError=ref('')
const selected=ref<ChatSession|null>(null),turns=ref<ChatTurn[]>([]),historyLoading=ref(false),historyError=ref('')
const draft=ref(''),busy=ref(false),creating=ref(false),removing=ref(''),progress=ref(''),streamError=ref(''),showDetail=ref(false)
const composer=ref<HTMLTextAreaElement|null>(null),timeline=ref<HTMLElement|null>(null),listPane=ref<HTMLElement|null>(null),showLatest=ref(false)
const citation=ref<ChatSource|null>(null),citationRequest=ref('')
let mounted=true,historyRevision=0,listRevision=0,historyController:AbortController|null=null,listScroll=0
const composing=ref(false)
interface Job { controller:AbortController;sessionId:string;turn:ChatTurn;requestId:string;cancelled:boolean;ended:boolean }
let active:Job|null=null,refreshTimer:ReturnType<typeof setInterval>|undefined
const currentTitle=computed(()=>selected.value?.title||'新会话')
const canSend=computed(()=>auth.has('ai:chat')&&auth.has('menu:ai'))
function live(job:Job){return mounted&&active===job&&!job.cancelled&&selected.value?.id===job.sessionId}
async function loadSessions(more=false){
  const revision=++listRevision;listLoading.value=true;listError.value=''
  const requestedPage=more?page.value+1:1
  try{const result=await chatApi.sessions(requestedPage);if(!mounted||revision!==listRevision)return;sessions.value=more?[...sessions.value,...result.items]:result.items;total.value=result.total;page.value=requestedPage;if(selected.value){const fresh=sessions.value.find(s=>s.id===selected.value?.id);if(fresh)selected.value=fresh}}
  catch(e){if(mounted&&revision===listRevision)listError.value=errorText(e)}
  finally{if(mounted&&revision===listRevision)listLoading.value=false}
}
async function loadHistory(id=selected.value?.id,quiet=false){
  historyController?.abort();const revision=++historyRevision
  if(!id)return
  historyController=new AbortController();if(!quiet)historyLoading.value=true;historyError.value=''
  try{const result=await chatApi.history(id,historyController.signal);if(!mounted||revision!==historyRevision||selected.value?.id!==id||active)return;const follow=!quiet||nearBottom();turns.value=result.items.map(turn=>({...turn,notice:turn.notice || (['partial_permission','partially_authorized','partial_restricted','partial_access','unauthorized_knowledge'].includes(turn.reason || '')?'回答仅依据当前有权阅读的知识，部分相关资料不在你的访问范围内。':turn.reason==='permission_changed'?'访问范围已变化，请重新提问。':undefined)}));if(follow)await scrollBottom()}
  catch(e){if(mounted&&revision===historyRevision&&!(e instanceof DOMException&&e.name==='AbortError')){historyError.value=e instanceof ApiError&&[403,404].includes(e.status)?'这段会话已不可访问，请选择其他会话。':errorText(e);if(e instanceof ApiError&&[403,404].includes(e.status))turns.value=[]}}
  finally{if(mounted&&revision===historyRevision)historyLoading.value=false}
}
function cancelJob(job:Job){job.cancelled=true;job.turn.status='cancelled';job.turn.assistant.content='';job.turn.assistant.sources=[];job.turn.external_sources=[];job.turn.notice=undefined;if(job.requestId)void chatApi.cancel(job.requestId).catch(()=>{});job.controller.abort();if(active===job){active=null;busy.value=false;progress.value=''}}
function stop(){if(active)cancelJob(active);void nextTick(()=>composer.value?.focus())}
async function confirmDraft(){if(!draft.value.trim())return true;try{await ElMessageBox.confirm('当前问题尚未发送，离开后会丢失已输入的内容。','保留未发送的问题',{confirmButtonText:'丢弃问题',cancelButtonText:'继续填写',type:'warning'});return true}catch{return false}}
async function choose(session:ChatSession){
  if(!await confirmDraft())return
  if(active)cancelJob(active)
  listScroll=listPane.value?.scrollTop||0;selected.value=session;turns.value=[];draft.value='';streamError.value='';citation.value=null;showDetail.value=true
  await loadHistory(session.id);await nextTick();composer.value?.focus()
}
async function newSession(){
  if(creating.value)return
  if(!await confirmDraft())return
  draft.value=''
  if(active)cancelJob(active)
  creating.value=true;streamError.value=''
  try{const session=await chatApi.create();if(!mounted)return;sessions.value=[session,...sessions.value];total.value++;await choose(session)}
  catch(e){streamError.value=errorText(e)}finally{if(mounted)creating.value=false}
}
async function removeSession(session:ChatSession){
  try{await ElMessageBox.confirm(`删除「${session.title}」后，此会话将无法继续查看。${selected.value?.id===session.id&&draft.value.trim()?'当前未发送的问题也会丢失。':''}`,'删除会话',{confirmButtonText:'删除会话',cancelButtonText:'保留会话',type:'warning'})}catch{return}
  removing.value=session.id
  if(active?.sessionId===session.id)cancelJob(active)
  try{await chatApi.remove(session.id);if(!mounted)return;sessions.value=sessions.value.filter(s=>s.id!==session.id);total.value=Math.max(0,total.value-1);if(selected.value?.id===session.id){historyController?.abort();historyRevision++;selected.value=null;turns.value=[];draft.value='';showDetail.value=false;historyError.value='';streamError.value='';citation.value=null}await loadSessions()}
  catch(e){listError.value=errorText(e)}finally{if(mounted)removing.value=''}
}
async function back(){showDetail.value=false;await nextTick();if(listPane.value)listPane.value.scrollTop=listScroll;listPane.value?.querySelector<HTMLElement>('[aria-current="true"]')?.focus()}
function nearBottom(){const el=timeline.value;return !el||el.scrollHeight-el.scrollTop-el.clientHeight<96}
function onScroll(){showLatest.value=!nearBottom()}
async function scrollBottom(){await nextTick();const el=timeline.value;if(el)el.scrollTop=el.scrollHeight;showLatest.value=false}
function accept(job:Job,event:ChatEvent){
  const data=event.data
  if(typeof data.request_id==='string'){job.requestId=data.request_id;job.turn.request_id=data.request_id;if(job.cancelled){void chatApi.cancel(data.request_id).catch(()=>{});return}}
  if(!live(job))return
  const follow=nearBottom()
  if(event.type==='meta'){job.turn.status='processing';progress.value='正在查找可用知识…'}
  if(event.type==='progress')progress.value=typeof data.message==='string'?data.message:'正在查找并核对知识来源…'
  if(event.type==='sources')job.turn.assistant.sources=Array.isArray(data.sources)?data.sources as ChatSource[]:[]
  if(event.type==='external_sources')job.turn.external_sources=safeExternalSources(data.sources)
  if(event.type==='delta'&&typeof data.text==='string'){job.turn.assistant.content+=data.text;progress.value='正在生成回答…'}
  if(event.type==='permission'){
    job.turn.notice=typeof data.message==='string'?data.message:'部分知识不在你的当前访问范围内。';job.turn.noticeCode=String(data.code||'permission')
    if(data.clear_answer){job.turn.assistant.content='';job.turn.assistant.sources=[];job.turn.external_sources=[];if(data.code==='permission_changed'){job.turn.assistant.redacted=true;job.turn.user.redacted=true;job.turn.user.content=''}}
  }
  if(event.type==='error'){job.turn.notice=typeof data.message==='string'?data.message:'生成未完成，请稍后重新提问。';if(data.clear_answer){job.turn.assistant.content='';job.turn.assistant.sources=[];job.turn.external_sources=[]}}
  if(event.type==='end'){
    job.ended=true;job.turn.status=String(data.status||'failed');job.turn.cache_status=String(data.cache_status||'miss')
    if(data.external_sources)job.turn.external_sources=safeExternalSources(data.external_sources)
    if(['cancelled','disconnected','permission_changed','restricted','error'].includes(job.turn.status)){job.turn.assistant.content='';job.turn.assistant.sources=[];job.turn.external_sources=[]}
    if(data.persisted===false){job.turn.assistant.content='';job.turn.assistant.sources=[];job.turn.external_sources=[];job.turn.notice='回答未能保存。请检查连接后重新提问。'}
    progress.value=''
  }
  if(follow)void scrollBottom()
}
async function send(){
  if(busy.value||creating.value||!canSend.value||!draft.value.trim())return
  const question=draft.value.trim();if(question.length>2000){streamError.value='问题最多可填写 2000 字。';return}
  streamError.value=''
  if(!selected.value){creating.value=true;try{const session=await chatApi.create();if(!mounted)return;selected.value=session;sessions.value=[session,...sessions.value];total.value++;showDetail.value=true}catch(e){streamError.value=errorText(e);return}finally{creating.value=false}}
  if(!mounted||!selected.value)return
  historyController?.abort();historyRevision++;historyLoading.value=false
  const turn:ChatTurn={request_id:'',status:'processing',user:{content:question},assistant:{content:'',sources:[]},created_at:new Date().toISOString()}
  turns.value.push(turn);const job:Job={controller:new AbortController(),sessionId:selected.value.id,turn:turns.value.at(-1)!,requestId:'',cancelled:false,ended:false};active=job;busy.value=true;draft.value='';progress.value='正在连接问答服务…';await scrollBottom()
  try{await streamChat(question,job.sessionId,job.controller.signal,event=>accept(job,event));if(live(job)&&!job.ended)throw new ApiError(0,'回答连接已中断，尚未收到完成确认。')}
  catch(e){if(live(job)){job.turn.status='failed';job.turn.assistant.content='';job.turn.assistant.sources=[];job.turn.external_sources=[];job.turn.notice=e instanceof ApiError?e.message:'回答连接已中断，请检查网络后重新提问。';if(job.requestId)void chatApi.cancel(job.requestId).catch(()=>{})}}
  finally{if(active===job){active=null;busy.value=false;progress.value='';if(mounted){void loadSessions();if(job.ended)void loadHistory(job.sessionId,true)}}}
}
async function confirmGap(turn:ChatTurn){if(!route.query.gap||verifying.value)return;verifying.value=true;try{await write(`/settlement/knowledge-gaps/${String(route.query.gap)}/status`,{status:'resolved',request_id:turn.request_id});ElMessage.success('已验证原问题，知识缺口已解决');await router.push({path:'/settlement',query:{tab:'gaps',status:'resolved'}})}catch(e){streamError.value=errorText(e)}finally{verifying.value=false}}
function keydown(e:KeyboardEvent){if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!composing.value&&e.keyCode!==229){e.preventDefault();void send()}}
function openCitation(turn:ChatTurn,source:ChatSource){citationRequest.value=turn.request_id;citation.value=source}
function revokedCitation(){const turn=turns.value.find(t=>t.request_id===citationRequest.value);if(turn){turn.user.content='';turn.user.redacted=true;turn.assistant.content='';turn.assistant.sources=[];turn.assistant.redacted=true}void loadHistory(selected.value?.id,true)}
function statusText(turn:ChatTurn){if(turn.assistant.redacted)return '来源已不可访问';if(turn.status==='completed'&&turn.cache_status==='hit')return 'FAQ 缓存回答';return ({processing:'生成中',completed:'已完成',cancelled:'已停止',disconnected:'连接中断',permission_changed:'访问范围已变化',restricted:'访问范围不足',no_match:'未找到依据',no_authorized_sources:'访问范围不足',low_confidence:'依据不足',error:'回答未完成',failed:'回答未完成'} as Record<string,string>)[turn.status]||'回答未完成'}
function refresh(){if(document.visibilityState==='visible'&&!busy.value){void loadSessions();if(selected.value)void loadHistory(selected.value.id,true)}}
function beforeUnload(e:BeforeUnloadEvent){if(draft.value.trim()){e.preventDefault();e.returnValue=''}}
onBeforeRouteLeave(()=>confirmDraft())
watch(canSend,allowed=>{if(!allowed){if(active)cancelJob(active);historyController?.abort();historyRevision++;turns.value=[];citation.value=null}})
onMounted(()=>{if(route.query.question){draft.value=String(route.query.question).slice(0,2000);showDetail.value=true}void loadSessions();window.addEventListener('focus',refresh);window.addEventListener('beforeunload',beforeUnload);document.addEventListener('visibilitychange',refresh);refreshTimer=setInterval(refresh,60000)})
onUnmounted(()=>{mounted=false;if(active)cancelJob(active);historyController?.abort();historyRevision++;listRevision++;clearInterval(refreshTimer);window.removeEventListener('focus',refresh);window.removeEventListener('beforeunload',beforeUnload);document.removeEventListener('visibilitychange',refresh)})
</script>
<template>
  <div class="chat-workbench" :class="{'chat-detail-open':showDetail}">
    <header class="page-head chat-page-head"><div><h1>AI 问答</h1><p>从有权阅读的知识中寻找答案，按来源核对。</p></div><button class="button" :disabled="creating||!canSend" @click="newSession"><Plus :size="16"/>{{creating?'创建中…':'新建会话'}}</button></header>
    <div class="chat-grid">
      <aside ref="listPane" class="chat-sessions" aria-label="历史会话">
        <div class="chat-section-head"><h2>历史会话</h2><button class="icon-button" aria-label="刷新历史会话" :disabled="listLoading" @click="loadSessions()"><RefreshCw :size="16"/></button></div>
        <p class="chat-list-count">{{total}} 段会话 · 仅本人可见</p>
        <div v-if="listError" class="chat-notice" role="alert"><p>{{listError}}</p><button class="text-button" @click="loadSessions()">重新加载</button></div>
        <div v-if="listLoading&&!sessions.length" class="chat-skeleton" role="status" aria-label="正在加载历史会话"><span v-for="i in 4" :key="i"></span></div>
        <div v-else-if="!sessions.length&&!listError" class="chat-list-empty"><MessageSquare :size="18"/><p>还没有历史会话</p><p>发送第一个问题后，会话会保存在这里。</p><button class="text-button" :disabled="creating||!canSend" @click="newSession">开始新会话</button></div>
        <ul class="chat-session-list"><li v-for="session in sessions" :key="session.id" :class="{selected:session.id===selected?.id}"><button class="chat-session-select" :aria-current="session.id===selected?.id?'true':undefined" @click="choose(session)"><strong>{{session.title}}</strong><span class="num">{{chatTime(session.updated_at)}}</span></button><button class="icon-button" :aria-label="`删除会话：${session.title}`" :disabled="removing===session.id" @click="removeSession(session)"><Trash2 :size="15"/></button></li></ul>
        <button v-if="sessions.length<total" class="text-button chat-more" :disabled="listLoading" @click="loadSessions(true)">{{listLoading?'加载中…':'加载更多会话'}}</button>
      </aside>
      <section class="chat-conversation" aria-label="当前问答">
        <header class="chat-conversation-head"><button class="icon-button chat-list-back" aria-label="返回历史会话" @click="back"><ArrowLeft :size="18"/></button><div><h2>{{currentTitle}}</h2><p>{{busy?'正在回答当前问题':selected?'可继续提问，或核对已有回答的来源':'制度、流程、技术知识都可以直接提问'}}</p></div><BookOpen :size="18" class="chat-book"/></header>
        <div ref="timeline" class="chat-timeline" @scroll="onScroll">
          <div v-if="historyError" class="chat-notice" role="alert"><p>{{historyError}}</p><button class="text-button" @click="loadHistory()">重新加载会话</button></div>
          <div v-else-if="historyLoading" class="chat-skeleton chat-history-skeleton" role="status" aria-label="正在读取会话"><span></span><span></span><span></span></div>
          <div v-else-if="!turns.length" class="chat-start"><h2>先把问题说清楚</h2><p>描述你要了解的制度、操作步骤或技术问题。回答会附上可读取的知识来源。</p><div class="chat-start-scope"><BookOpen :size="17"/><p>答案依据当前已发布、且向你开放的知识。没有足够依据时，会明确说明。</p></div></div>
          <article v-for="(turn,index) in turns" :key="turn.request_id||index" class="chat-turn">
            <div class="chat-question"><div class="chat-message-head"><strong>我的问题</strong><time class="num">{{chatTime(turn.created_at)}}</time></div><p>{{turn.user.redacted?'此轮涉及的知识已不可访问，问题内容不再显示。':turn.user.content}}</p></div>
            <div class="chat-answer"><div class="chat-message-head"><strong>知识回答</strong><span class="chat-turn-status" :class="{'chat-status-running':turn.status==='processing'}">{{statusText(turn)}}</span></div><ChatMarkdown v-if="turn.assistant.content" :content="turn.assistant.content"/><p v-else-if="turn.assistant.redacted" class="chat-answer-empty">此轮来源已撤销发布或访问权限，回答与引用不再显示。</p><p v-else-if="turn.status==='processing'" class="chat-answer-empty">{{progress||'正在查找可用知识…'}}</p><p v-else-if="turn.status==='cancelled'" class="chat-answer-empty">已停止生成，可以修改问题后重新发送。</p><p v-else-if="turn.status==='low_confidence'" class="chat-answer-empty">当前知识依据不足，请补充问题背景或联系知识负责人。</p><p v-else-if="['no_authorized_sources','restricted'].includes(turn.status)" class="chat-answer-empty">当前访问范围内没有足够的知识依据，请联系知识负责人。</p><p v-else-if="turn.status==='no_match'" class="chat-answer-empty">没有找到可以支持回答的知识，请换一种描述或补充相关资料。</p><p v-else class="chat-answer-empty">回答未完成，请稍后重新提问。</p><div v-if="turn.notice || turn.permission_hint?.message" class="chat-notice" role="status"><p>{{turn.notice || turn.permission_hint?.message}}</p></div>
              <div v-if="turn.status==='completed'&&route.query.gap" class="settlement-verification"><button class="button" :disabled="verifying" @click="confirmGap(turn)">{{verifying?'正在核对来源…':'用此回答确认补全'}}</button><RouterLink :to="{path:'/settlement',query:{tab:'gaps'}}" class="text-button">返回知识缺口确认结果</RouterLink></div><div v-if="turn.assistant.sources?.length" class="chat-sources"><h3>知识来源 <span class="num">{{turn.assistant.sources.length}}</span></h3><ol><li v-for="(source,i) in turn.assistant.sources" :key="source.chunk_id"><button class="chat-source-button" :disabled="turn.status!=='completed'" @click="openCitation(turn,source)"><span class="chat-source-number num">{{source.citation || i+1}}</span><span><strong>{{source.title}}</strong><small>{{sourcePosition(source.position)}}</small></span><span class="chat-source-action">{{turn.status==='processing'?'完成后可核对':'查看来源'}}</span></button></li></ol></div>
              <div v-if="turn.external_sources?.length && !turn.assistant.redacted" class="chat-external-sources"><h3>外部搜索结果</h3><p>外部搜索结果，不作为内部制度依据。</p><ul><li v-for="source in safeExternalSources(turn.external_sources)" :key="source.url"><a :href="source.url" target="_blank" rel="noopener noreferrer">{{source.title}}</a><p v-if="source.snippet">{{source.snippet}}</p></li></ul></div>
            </div>
          </article>
        </div>
        <button v-if="showLatest" class="text-button chat-latest" @click="scrollBottom"><ArrowDown :size="15"/>回到最新回答</button>
        <form class="chat-composer" @submit.prevent="send"><label for="chat-question">{{busy?'回答生成中':'继续提问'}}</label><textarea id="chat-question" ref="composer" v-model="draft" rows="3" maxlength="2000" aria-describedby="chat-input-hint" placeholder="输入你的问题，尽量说明背景与想了解的内容" :disabled="!canSend||creating" @keydown="keydown" @compositionstart="composing=true" @compositionend="composing=false"></textarea><p v-if="streamError" class="chat-form-error" role="alert">{{streamError}}</p><p v-if="!canSend" class="chat-form-error" role="status">当前账号没有提问权限，请联系管理员。</p><div class="chat-composer-foot"><p id="chat-input-hint">Enter 发送 · Shift + Enter 换行</p><button v-if="busy" type="button" class="button" @click="stop"><Square :size="14"/>停止生成</button><button v-else class="button primary" :disabled="!draft.trim()||creating||!canSend"><ArrowUp :size="16"/>发送问题</button></div><p class="chat-response-hint" role="status" aria-live="polite">{{busy?progress:'回答可能存在遗漏，请结合知识来源核对。'}}</p></form>
      </section>
    </div>
    <ChatCitationDialog :source="citation" :request-id="citationRequest" @close="citation=null" @revoked="revokedCitation"/>
  </div>
</template>
