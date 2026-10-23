<script setup lang="ts">
defineProps<{ label: string; tableClass?: string }>()
</script>
<template>
  <div class="data-table-wrap"><table class="data-table" :class="tableClass" :aria-label="label"><thead><slot name="head" /></thead><tbody><slot /></tbody></table></div>
</template>
