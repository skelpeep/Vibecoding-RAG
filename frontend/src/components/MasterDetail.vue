<script setup lang="ts">
defineProps<{ showDetail: boolean }>()
</script>
<template><div class="master-detail" :class="{'show-detail':showDetail}"><section class="master-pane"><slot name="master" /></section><section class="detail-pane"><slot /></section></div></template>
