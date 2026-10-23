<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{name: string; identity: string}>()
const colors = ['#e5eef0','#f0e8e2','#e9ece2','#ece8ed','#e5eaf1','#f0e5e7']
const color = computed(() => colors[Array.from(props.identity).reduce((n,c) => n+c.charCodeAt(0),0) % colors.length])
</script>
<template><span class="avatar" :style="{background:color}" aria-hidden="true">{{ name.slice(0,1) }}</span></template>
