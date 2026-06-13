import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import axios from 'axios'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import './styles/global.css'

import App from './App.vue'
import router from './router'
import { pinia } from './stores'

const PUBLIC_PATHS = new Set(['/login', '/register'])

axios.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && !PUBLIC_PATHS.has(window.location.pathname)) {
      delete axios.defaults.headers.common.Authorization
      localStorage.removeItem('hbbwater_access_token')
      const redirect = encodeURIComponent(`${window.location.pathname}${window.location.search}`)
      window.location.replace(`/login?redirect=${redirect}`)
    }
    return Promise.reject(error)
  }
)

const app = createApp(App)

// Register all Element Plus icons
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(pinia)
app.use(router)
app.use(ElementPlus)

app.mount('#app')
