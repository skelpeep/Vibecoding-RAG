<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import '../vendor/taste-charts.js'
const props=defineProps<{labels:string[];values:(number|null)[];name:string}>()
const root=ref<HTMLElement|null>(null)
let observer:ResizeObserver|undefined
const chartWindow=window as unknown as {Charts:{line:(element:HTMLElement,data:unknown)=>void}}
function draw(){if(!root.value)return;const max=Math.max(0,...props.values.filter((v):v is number=>v!==null)),raw=Math.max(1,(max+1)/4),magnitude=10**Math.floor(Math.log10(raw));const step=([1,2,5,10].map(n=>n*magnitude).find(n=>n>=raw)||10*magnitude);chartWindow.Charts.line(root.value,{labels:props.labels,series:[{name:props.name,values:props.values}],yTicks:[0,step,step*2,step*3,step*4],format:(v:number)=>new Intl.NumberFormat('zh-CN').format(v),height:145})}
watch(()=>[props.labels,props.values],()=>void nextTick(draw),{deep:true})
onMounted(async()=>{await document.fonts.ready;draw();observer=new ResizeObserver(draw);if(root.value)observer.observe(root.value)})
onUnmounted(()=>observer?.disconnect())
</script>
<template><div ref="root" class="data-chart" :aria-label="name"></div><p v-if="values.every(value=>value===null)" class="quiet-empty">当前范围暂无可用数据。</p></template>
