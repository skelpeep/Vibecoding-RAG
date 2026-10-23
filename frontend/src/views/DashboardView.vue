<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import PageHeader from '../components/PageHeader.vue'
import AsyncState from '../components/AsyncState.vue'
import DataChart from '../components/DataChart.vue'
import { request, errorText } from '../api'
import { number, type Dashboard } from '../settlement'
import '../settlement.css'
const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date())
const from=new Date(`${today}T00:00:00Z`);from.setUTCDate(from.getUTCDate()-6)
const form=reactive({start:from.toISOString().slice(0,10),end:today,bucket:'day'})
const data=ref<Dashboard|null>(null),loading=ref(true),error=ref('')
let alive=true,revision=0
async function load(){const rev=++revision;loading.value=true;error.value='';try{const value=await request<Dashboard>(`/dashboard/overview?${new URLSearchParams({...form,timezone:'Asia/Shanghai'})}`);if(alive&&rev===revision)data.value=value}catch(e){if(alive&&rev===revision){data.value=null;error.value=errorText(e)}}finally{if(alive&&rev===revision)loading.value=false}}
const labels=computed(()=>data.value?.trends.map(p=>p.date.slice(5))||[])
onMounted(load);onUnmounted(()=>{alive=false;revision++})
</script>
<template><div class="analytics-screen">
  <PageHeader title="数据看板" description="从提问到可靠答案，查看知识库的实际使用情况。"><button class="button" :disabled="loading" @click="load"><RefreshCw :size="15"/>刷新</button></PageHeader>
  <form class="analytics-filter" @submit.prevent="load"><label>开始日期<input v-model="form.start" type="date" required :max="form.end"/></label><label>结束日期<input v-model="form.end" type="date" required :min="form.start"/></label><label>聚合方式<select v-model="form.bucket"><option value="day">按日</option><option value="week">按周</option></select></label><button class="button" :disabled="loading">应用范围</button><span class="muted">北京时间</span></form>
  <AsyncState :loading="loading" :error="error" @retry="load"><template v-if="data">
    <div class="metric-strip"><div><span>Agent 访问次数</span><strong class="num lead-number">{{number(data.metrics.visits)}}</strong></div><div><span>独立访问人数</span><strong class="num">{{number(data.metrics.unique_users)}}</strong></div><div><span>当前知识单元</span><strong class="num">{{number(data.metrics.knowledge_units)}}</strong></div><div><span>已知 Token 消耗</span><strong class="num">{{number(data.metrics.total_tokens)}}</strong></div><div><span>平均响应时间</span><strong class="num">{{number(data.metrics.average_response_ms,0)}} <small>ms</small></strong></div></div>
    <div class="answer-flow" aria-label="回答结果"><span>有依据回答 <b class="num">{{number(data.metrics.completed)}}</b></span><span>FAQ 命中 <b class="num">{{number(data.metrics.cache_hits)}}</b></span><span>依据不足 <b class="num">{{number(data.metrics.unanswered)}}</b></span><span>权限受限 <b class="num">{{number(data.metrics.restricted)}}</b></span><span>失败 / 取消 <b class="num">{{number(data.metrics.failed)}} / {{number(data.metrics.cancelled)}}</b></span></div>
    <div class="analytics-grid"><section><h2>访问趋势</h2><DataChart :labels="labels" :values="data.trends.map(p=>p.visits)" name="Agent 访问次数"/></section><section><h2>Token 消耗趋势</h2><DataChart :labels="labels" :values="data.trends.map(p=>p.tokens)" name="已知 Token 消耗"/></section>
    <section><h2>响应时间趋势（ms）</h2><DataChart :labels="labels" :values="data.trends.map(p=>p.average_response_ms)" name="平均响应时间（毫秒）"/></section>
    <section><h2>常见问题</h2><p v-if="!data.questions.length" class="quiet-empty">当前范围没有可展示的问题。问题需拥有全部来源访问权。</p><ol v-else class="rank-list"><li v-for="row in data.questions" :key="row.question"><span>{{row.question}}</span><strong class="num">{{number(row.count)}} 次</strong></li></ol></section>
    <section><h2>知识热度</h2><p v-if="!data.units.length" class="quiet-empty">当前范围没有你可读取的知识引用。</p><ol v-else class="rank-list"><li v-for="row in data.units" :key="row.unit_id"><RouterLink :to="`/knowledge/${row.unit_id}`">{{row.title}}</RouterLink><strong class="num">{{number(row.count)}} 次</strong></li></ol></section>
    <section><h2>响应时间分布</h2><div class="latency-list"><div v-for="bin in data.latency" :key="bin.label"><span>{{bin.label}}</span><div class="latency-track"><span :style="{width:`${Math.max(...data.latency.map(b=>b.count))?bin.count/Math.max(...data.latency.map(b=>b.count))*100:0}%`}"></span></div><strong class="num">{{number(bin.count)}}</strong></div></div></section>
    <section class="metric-notes"><h2>统计口径</h2><p>{{data.range.start}} 至 {{data.range.end}} · Asia/Shanghai</p><p>用量未知 <b class="num">{{number(data.metrics.unknown_usage)}}</b> 次，部分用量 <b class="num">{{number(data.metrics.partial_usage)}}</b> 次。Token 为已知值之和。</p><p>访问包含失败与取消；耗时只计算已结束请求。知识总量为当前未删除文档，包含草稿。</p><details><summary>查看完整定义</summary><p v-for="(value,key) in data.definitions" :key="key">{{value}}</p></details></section></div>
  </template></AsyncState>
</div></template>
