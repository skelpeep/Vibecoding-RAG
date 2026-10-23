<script setup lang="ts">
import { computed } from 'vue'
import type { Attachment } from '../knowledge'
import KnowledgeImage from './KnowledgeImage.vue'
const props=defineProps<{content:string;files:Attachment[];allowImages:boolean}>(),emit=defineEmits<{unavailable:[]}>()
const parts=computed(()=>{
 const result:({type:'text';text:string}|{type:'image';file:Attachment;alt:string})[]=[]
 const pattern=/!\[([^\]]*)\]\(\/api\/knowledge\/files\/([a-fA-F0-9-]{36})\/image\)/g
 let offset=0,match:RegExpExecArray|null
 while((match=pattern.exec(props.content))){const file=props.files.find(file=>file.id===match![2]&&file.image_url);if(!file||!props.allowImages)continue;if(match.index>offset)result.push({type:'text',text:props.content.slice(offset,match.index)});result.push({type:'image',file,alt:match[1]||file.file_name});offset=pattern.lastIndex}
 if(offset<props.content.length)result.push({type:'text',text:props.content.slice(offset)})
 return result
})
const extraImages=computed(()=>props.allowImages?props.files.filter(file=>file.image_url&&!parts.value.some(part=>part.type==='image'&&part.file.id===file.id)):[])
</script>
<template><article class="knowledge-body" aria-label="知识正文"><template v-for="(part,index) in parts" :key="index"><p v-if="part.type==='text'" class="document-content">{{part.text}}</p><KnowledgeImage v-else :file-id="part.file.id" :name="part.alt" @unavailable="emit('unavailable')"/></template><div v-if="extraImages.length" class="knowledge-images"><KnowledgeImage v-for="file in extraImages" :key="file.id" :file-id="file.id" :name="file.file_name" @unavailable="emit('unavailable')"/></div></article></template>
