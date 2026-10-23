<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../stores/auth'
import PageHeader from '../components/PageHeader.vue'
const route=useRoute(),router=useRouter(),auth=useAuth()
const description=computed(()=>route.path==='/forbidden'?'当前账号没有访问此页面的权限，请联系组织管理员。':route.path==='/unavailable'?'暂时无法连接组织服务，请稍后重试。':'该页面可能已移动，请从导航进入工作区。')
function retry(){const path=String(route.query.redirect||auth.home());void router.replace(path.startsWith('/')&&!path.startsWith('//')?path:auth.home())}
</script>
<template><PageHeader :title="String(route.meta.title)"/><div class="empty-state status-page"><p>{{description}}</p><button v-if="route.path==='/unavailable'" class="button" @click="retry">重新连接</button><RouterLink v-else :to="auth.home()" class="button">返回工作区</RouterLink></div></template>
