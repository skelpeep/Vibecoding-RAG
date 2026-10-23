<script setup lang="ts">
import { useId } from 'vue'
const id = useId()
defineProps<{label: string; hint?: string; required?: boolean}>()
</script>
<template><div class="field"><label :for="id">{{ label }}<span v-if="required" class="required-dot"> *</span></label><slot :id="id" /><small v-if="hint">{{ hint }}</small></div></template>
