import { createRouter, createWebHashHistory } from 'vue-router'

import { useUserStore } from '@/stores/user'

// 本地存储键（与 stores/user.js 保持一致）
const TOKEN_KEY = 'cd_pc_token'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginPage.vue'),
    meta: { requiresAuth: false, title: '管理员登录' },
  },
  {
    path: '/',
    component: () => import('@/layouts/AdminLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardPage.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '实时监控大屏' },
      },
      {
        path: 'feedback',
        name: 'feedback',
        component: () => import('@/views/FeedbackPage.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '反馈工单中心' },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/UsersPage.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '用户管理' },
      },
      {
        path: 'warning',
        name: 'warning',
        component: () => import('@/views/WarningPage.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '预警中心' },
      },
      {
        path: 'detections',
        name: 'detections',
        component: () => import('@/views/DetectionsPage.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '检测记录管理' },
      },
      {
        path: 'knowledge',
        name: 'knowledge',
        component: () => import('@/views/KnowledgePage.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '知识库管理' },
      },
      {
        path: 'model',
        name: 'model',
        component: () => import('@/views/ModelPage.vue'),
        meta: { requiresAuth: true, requiresAdmin: true, title: '模型管理' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
]

const router = createRouter({
  // 单页应用使用 hash 模式：静态部署无需服务端 rewrite，跳登录也更稳
  history: createWebHashHistory(),
  routes,
})

/**
 * 全局前置守卫：
 * - 受保护路由（meta.requiresAuth）无 token → 重定向 /login
 * - meta.requiresAdmin 且当前用户非 admin → 提示并回登录（PC 仅管理员）
 * - 已登录访问 /login → 直接进入大屏
 */
router.beforeEach((to) => {
  const hasToken = !!localStorage.getItem(TOKEN_KEY)
  if (to.meta.requiresAuth && !hasToken) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.requiresAdmin && hasToken) {
    const userStore = useUserStore()
    if (userStore.user && userStore.user.role !== 'admin') {
      userStore.logout()
      return { name: 'login', query: { redirect: to.fullPath, denied: '1' } }
    }
  }
  if (to.name === 'login' && hasToken) {
    return { name: 'dashboard' }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `作物医生 · ${to.meta.title}` : '作物医生 · 管理控制台'
})

export default router
