<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { ApiError, authorizedBlob, errorText } from '../api'
const props=defineProps<{fileId:string;name:string}>(),emit=defineEmits<{unavailable:[]}>()
const url=ref(''),error=ref(''),loading=ref(true)
let controller:AbortController|null=null,interval:ReturnType<typeof setInterval>,generation=0
function clear(){if(url.value)URL.revokeObjectURL(url.value);url.value=''}
async function load(){const current=++generation;controller?.abort();controller=new AbortController();if(!url.value)loading.value=true;error.value='';try{const blob=await authorizedBlob(`/knowledge/files/${props.fileId}/image`,controller.signal);if(current!==generation)return;clear();url.value=URL.createObjectURL(blob)}catch(e){if(current!==generation)return;clear();error.value=errorText(e);if(e instanceof ApiError&&[401,403,404].includes(e.status))emit('unavailable')}finally{if(current===generation)loading.value=false}}
watch(()=>props.fileId,()=>{clear();void load()})
onMounted(()=>{void load();interval=setInterval(()=>{if(document.visibilityState==='visible')void load()},15000)})
onUnmounted(()=>{generation++;controller?.abort();clearInterval(interval);clear()})
</script>
<template><figure class="knowledge-image"><img v-if="url" :src="url" :alt="name"/><div v-else-if="loading" class="notice" role="status">正在读取图片…</div><div v-else-if="error" class="notice" role="alert">图片暂不可用。<button class="text-button" @click="load">重试</button></div><figcaption>{{name}}</figcaption></figure></template>
