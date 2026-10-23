<script setup lang="ts">
import { computed } from 'vue'
import { Marked } from 'marked'
import DOMPurify from 'dompurify'
const props=defineProps<{content:string}>()
const renderer:Marked=new Marked({breaks:true,gfm:true,renderer:{html:()=>'',image:()=>'',heading:({tokens,depth}):string=>`<h${Math.min(depth+1,4)}>${renderer.parseInline(tokens.map(token=>token.raw).join(''))}</h${Math.min(depth+1,4)}>`}})
const html=computed(()=>DOMPurify.sanitize(renderer.parse(props.content,{async:false}) as string,{ALLOWED_TAGS:['p','br','strong','em','del','h1','h2','h3','h4','ul','ol','li','blockquote','pre','code','table','thead','tbody','tr','th','td','a','hr'],ALLOWED_ATTR:['href','title'],ALLOW_DATA_ATTR:false,ALLOW_ARIA_ATTR:false,ALLOWED_URI_REGEXP:/^(?:https?:|mailto:|#)/i}))
</script>
<template><div class="chat-markdown" v-html="html"></div></template>
