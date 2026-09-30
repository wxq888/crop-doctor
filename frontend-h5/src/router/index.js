import { createRouter, createWebHashHistory } from 'vue-router'

// 本地存储键（与 stores/user.js 保持一致）
const TOKEN_KEY = 'cd_token'

const routes = [
  { path: '/', redirect: '/home' },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginPage.vue'),
    meta: { requiresAuth: false, title: '登录 / 注册' },
  },
  // ===== 5 个一级 Tab（底部导航，meta.tabbar 控制是否显示 TabBar） =====
  {
    path: '/home',
    name: 'home',
    component: () => import('@/views/HomePage.vue'),
    meta: { requiresAuth: true, title: '首页', tabbar: true },
  },
  {
    path: '/records',
    name: 'records',
    component: () => import('@/views/RecordsPage.vue'),
    meta: { requiresAuth: true, title: '检测记录', tabbar: true },
  },
  {
    path: '/chat',
    name: 'chat',
    component: () => import('@/views/ChatPage.vue'),
    meta: { requiresAuth: true, title: '智能问诊', tabbar: true },
  },
  {
    path: '/knowledge',
    name: 'knowledge',
    component: () => import('@/views/KnowledgePage.vue'),
    meta: { requiresAuth: true, title: '知识库', tabbar: true },
  },
  {
    path: '/mine',
    name: 'mine',
    component: () => import('@/views/MinePage.vue'),
    meta: { requiresAuth: true, title: '我的', tabbar: true },
  },
  // ===== 二级页 =====
  {
    path: '/realtime',
    name: 'realtime',
    component: () => import('@/views/RealtimePage.vue'),
    meta: { requiresAuth: true, title: '摄像头实时检测' },
  },
  {
    path: '/detection/:id',
    name: 'detection-detail',
    component: () => import('@/views/DetectionDetailPage.vue'),
    meta: { requiresAuth: true, title: '检测结果' },
  },
  {
    path: '/alerts',
    name: 'alerts',
    component: () => import('@/views/AlertsPage.vue'),
    meta: { requiresAuth: true, title: '预警消息' },
  },
  {
    path: '/weather',
    name: 'weather',
    component: () => import('@/views/WeatherPage.vue'),
    meta: { requiresAuth: true, title: '天气详情' },
  },
  {
    path: '/feedbacks',
    name: 'feedbacks',
    component: () => import('@/views/FeedbackListPage.vue'),
    meta: { requiresAuth: true, title: '我的反馈' },
  },
  {
    path: '/feedbacks/:id',
    name: 'feedback-detail',
    component: () => import('@/views/FeedbackDetailPage.vue'),
    meta: { requiresAuth: true, title: '反馈详情' },
  },
  {
    path: '/knowledge/docs/:id',
    name: 'knowledge-doc',
    component: () => import('@/views/KnowledgeDocPage.vue'),
    meta: { requiresAuth: true, title: '知识文档' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsPage.vue'),
    meta: { requiresAuth: true, title: '设置' },
  },
  {
    path: '/about',
    name: 'about',
    component: () => import('@/views/AboutPage.vue'),
    meta: { requiresAuth: true, title: '关于' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/home' },
]

const router = createRouter({
  // H5 单页应用使用 hash 模式：静态部署无需服务端 rewrite，401 跳转也更稳
  history: createWebHashHistory(),
  routes,
})

/**
 * 全局前置守卫：
 * - 受保护路由（meta.requiresAuth）无 token → 重定向 /login 并记录来源
 * - 已登录访问 /login → 直接进入首页
 */
router.beforeEach((to) => {
  const hasToken = !!localStorage.getItem(TOKEN_KEY)
  if (to.meta.requiresAuth && !hasToken) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && hasToken) {
    return { name: 'home' }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `作物医生 · ${to.meta.title}` : '作物医生'
})

export default router
