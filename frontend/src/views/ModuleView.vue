<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { BookOpen } from 'lucide-vue-next'
import PageHeader from '../components/PageHeader.vue'
const route=useRoute()
const content=computed(()=>({ '/knowledge':{description:'维护知识文档与访问范围。',future:'文档导入、版本管理和知识授权将在后续开放。'},'/chat':{description:'在自己的访问范围内查找答案。',future:'问答、历史会话和来源引用将在后续开放。'},'/dashboard':{description:'了解知识库的使用情况。',future:'访问趋势、知识热度和消耗统计将在后续开放。'},'/settlement':{description:'让重复问题沉淀为共享知识。',future:'FAQ 审核、已发布知识和知识缺口将在后续开放。'} }[route.path]||{description:'',future:''}))
</script>
<template><PageHeader :title="String(route.meta.title)" :description="content.description"/><div class="module-empty"><BookOpen :size="28" :stroke-width="1.3"/><h2>此功能尚未开放</h2><p>{{content.future}}</p><RouterLink to="/profile" class="button">查看我的身份与权限</RouterLink></div></template>
