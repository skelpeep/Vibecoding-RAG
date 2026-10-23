import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@fontsource/ibm-plex-sans/latin-400.css'
import '@fontsource/ibm-plex-sans/latin-500.css'
import '@fontsource/ibm-plex-sans/latin-600.css'
import '@fontsource-variable/noto-sans-sc'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import './style.css'
import './knowledge.css'
import App from './App.vue'
import { router } from './router'
import { setAuthHandlers } from './api'
import { useAuth } from './stores/auth'

const app=createApp(App)
app.use(createPinia())
setAuthHandlers(() => {useAuth().clear(); void router.replace({path:'/login',query:{expired:'1'}})}, () => {void useAuth().refresh().catch(()=>{})})
app.use(router).mount('#app')
