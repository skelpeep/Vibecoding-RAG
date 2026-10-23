<script setup lang="ts">
import { ElDialog } from 'element-plus'
defineProps<{open:boolean; title:string; busy?:boolean; error?:string; submitLabel?:string}>()
defineEmits<{close:[]; submit:[]}>()
</script>
<template><ElDialog :model-value="open" :title="title" width="540px" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" destroy-on-close @close="$emit('close')"><form @submit.prevent="$emit('submit')"><slot /><p v-if="error" class="form-error" role="alert">{{ error }}</p><div class="form-actions"><button type="button" class="button" :disabled="busy" @click="$emit('close')">取消</button><button class="button primary" :disabled="busy">{{ busy ? '保存中…' : submitLabel || '保存' }}</button></div></form></ElDialog></template>
