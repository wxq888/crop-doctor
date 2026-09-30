import { createApp } from 'vue'
import { createPinia } from 'pinia'

// 全局引入 Vant 4 组件与样式（依赖精简，不做按需引入）
import Vant from 'vant'
import 'vant/lib/index.css'

import App from './App.vue'
import router from './router'

// Design Token 必须在 Vant 样式之后引入，才能覆盖其 CSS 变量
import './styles/tokens.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(Vant)

app.mount('#app')
