import { createApp } from 'vue'
import { createPinia } from 'pinia'

// Element Plus：全局引入组件 + 基础样式 + 官方暗色变量 + 中文语言包
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

import App from './App.vue'
import router from './router'

// Design Token 必须在 Element Plus 样式之后引入，才能覆盖其 CSS 变量
import './styles/tokens.css'
import './styles/element-dark.css'
import './styles/index.css'

// 首屏主题：读取 localStorage 并应用到 <html>，避免闪色（§7.4）
import { initTheme } from './utils/theme'

initTheme()

const app = createApp(App)

app.use(createPinia())
app.use(router)
// 指定中文语言包（分页 / 日期 / 空态等文案中文化）
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
