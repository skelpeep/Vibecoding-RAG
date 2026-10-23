<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Eye, EyeOff, Users, Network, ShieldCheck } from 'lucide-vue-next'
import { useAuth } from '../stores/auth'
import { errorText } from '../api'
import BrandMark from '../components/BrandMark.vue'
const username=ref(''),password=ref(''),visible=ref(false),busy=ref(false),error=ref('')
const auth=useAuth(),route=useRoute(),router=useRouter()
async function login() {
  busy.value=true;error.value=''
  try { await auth.login(username.value.trim(),password.value); password.value=''; const target=String(route.query.redirect || ''); await router.replace(target.startsWith('/') && !target.startsWith('//') && target !== '/login' ? target : auth.home()) }
  catch(e) { error.value=errorText(e) } finally {busy.value=false}
}
</script>
<template>
  <div class="login-page"><header class="login-top"><div class="brand"><BrandMark/><span>知识库管理平台</span></div><span class="muted">组织知识 · 有序共享</span></header>
    <main class="login-card"><section class="login-intro"><div class="login-symbol"><BrandMark /></div><h2>每一份知识，<br/>都有合适的访问范围。</h2><p>连接组织成员与知识，让经验在清晰的权限下流动。</p><div class="identity-demo"><div><Users :size="18"/><span>成员身份</span></div><ArrowRight :size="16"/><div><Network :size="18"/><span>所属部门</span></div><ArrowRight :size="16"/><div><ShieldCheck :size="18"/><span>角色权限</span></div></div><span class="login-intro-note">以个人账号登录组织工作区</span></section>
    <section class="login-form"><h1>登录工作区</h1><p class="muted">使用管理员分配的账号继续。</p><p v-if="route.query.expired" class="notice" role="status">登录已失效，请重新登录。</p><form @submit.prevent="login"><div class="field"><label for="username">用户名</label><input id="username" v-model="username" required autocomplete="username" autofocus placeholder="输入用户名" maxlength="64" /></div><div class="field"><label for="password">密码</label><div class="password-input"><input id="password" v-model="password" :type="visible?'text':'password'" required autocomplete="current-password" placeholder="输入密码" maxlength="128"/><button type="button" class="icon-button" :aria-label="visible?'隐藏密码':'显示密码'" @click="visible=!visible"><EyeOff v-if="visible" :size="18"/><Eye v-else :size="18"/></button></div></div><p v-if="error" class="form-error" role="alert">{{ error }}</p><button class="button primary login-submit" :disabled="busy">{{busy?'正在登录…':'登录'}}<ArrowRight :size="17"/></button></form><p class="login-help">无法登录？请联系组织管理员检查账号状态。</p></section></main><footer class="login-footer">知识库管理平台 · 组织工作区</footer></div>
</template>
