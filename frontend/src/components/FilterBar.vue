<script setup lang="ts">
defineProps<{ label?: string }>()
</script>
<template><div class="toolbar" role="search" :aria-label="label || '筛选列表'"><slot /><div class="toolbar-end"><slot name="end" /></div></div></template>
