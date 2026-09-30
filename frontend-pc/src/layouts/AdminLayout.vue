<script setup>
/**
 * 管理端整体框架（ui-design.md §4.1）：
 * 左侧固定深色导航（el-menu）+ 顶部信息条（用户 / 主题切换）+ 主工作区。
 * WS 在此层建立（全站常驻），以驱动导航「待回复工单」角标（§7.6）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox, ElMessage } from 'element-plus'

import { useUserStore } from '@/stores/user'
import { useMonitorStore } from '@/stores/monitor'
import request from '@/api/request'
import ThemeToggle from '@/components/common/ThemeToggle.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const monitorStore = useMonitorStore()

/** 左侧导航项（顺序即信息架构） */
const navItems = [
  { index: '/dashboard', label: '实时监控大屏', icon: '📊' },
  { index: '/feedback', label: '反馈工单中心', icon: '💬' },
  { index: '/warning', label: '预警中心', icon: '⚠️' },
  { index: '/detections', label: '检测记录管理', icon: '🔍' },
  { index: '/users', label: '用户管理', icon: '👥' },
  { index: '/knowledge', label: '知识库管理', icon: '📚' },
  { index: '/model', label: '模型管理', icon: '🧠' },
]

/** 当前激活菜单 = 当前路由路径 */
const activeMenu = computed(() => route.path)

/** 待回复工单角标 */
const pendingCount = ref(0)

/** 拉取管理员未读工单数（GET /admin/feedback/unread-count） */
async function loadPendingCount() {
  try {
    const data = await request.get('/admin/feedback/unread-count')
    pendingCount.value = (data && data.count) || 0
  } catch (e) {
    // 角标失败静默，不打扰主流程
  }
}

// WS 工单事件到达时刷新角标
watch(
  () => monitorStore.feedbackDelta,
  () => loadPendingCount(),
)

/** 退出登录（二次确认） */
async function handleLogout() {
  try {
    await ElMessageBox.confirm('确认退出当前管理员账号？', '退出登录', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch (e) {
    return
  }
  monitorStore.disconnect()
  monitorStore.reset()
  userStore.logout()
  ElMessage.success('已退出登录')
  router.replace({ name: 'login' })
}

/** 顶部信息条左侧当前页标题 */
const pageTitle = computed(() => route.meta.title || '管理控制台')

onMounted(() => {
  // 全站常驻 WS（幂等），驱动角标与事件流
  monitorStore.connect()
  loadPendingCount()
})
</script>

<template>
  <div class="admin-layout">
    <!-- 左侧固定导航 -->
    <aside class="admin-nav">
      <div class="admin-nav__brand">
        <span class="admin-nav__logo">🌱</span>
        <div class="admin-nav__brand-text">
          <div class="admin-nav__brand-name">作物医生</div>
          <div class="admin-nav__brand-sub">CROPDOCTOR ADMIN</div>
        </div>
      </div>
      <el-menu
        class="admin-nav__menu"
        :default-active="activeMenu"
        :router="true"
        background-color="var(--pc-nav)"
        text-color="var(--pc-nav-text)"
        active-text-color="var(--pc-nav-active)"
      >
        <el-menu-item v-for="item in navItems" :key="item.index" :index="item.index">
          <span class="admin-nav__icon">{{ item.icon }}</span>
          <span class="admin-nav__label">{{ item.label }}</span>
          <el-badge
            v-if="item.index === '/feedback' && pendingCount > 0"
            :value="pendingCount"
            :max="99"
            class="admin-nav__badge"
          />
        </el-menu-item>
      </el-menu>
      <div class="admin-nav__foot">v1.0 · 仅限授权管理员</div>
    </aside>

    <!-- 右侧主区 -->
    <div class="admin-main">
      <header class="admin-topbar">
        <div class="admin-topbar__title">{{ pageTitle }}</div>
        <div class="admin-topbar__right">
          <span class="admin-topbar__live" :class="{ 'is-on': monitorStore.connected }">
            <i class="admin-topbar__dot" />{{ monitorStore.connected ? '● LIVE' : '○ 离线' }}
          </span>
          <ThemeToggle />
          <el-dropdown trigger="click">
            <span class="admin-topbar__user">
              <span class="admin-topbar__avatar">{{ (userStore.displayName || 'A').slice(0, 1) }}</span>
              <span class="admin-topbar__name">{{ userStore.displayName }}</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>{{ userStore.user?.username || 'admin' }}</el-dropdown-item>
                <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>
      <main class="admin-workspace">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.admin-layout {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background-color: var(--pc-bg);
}

/* ---------- 左侧导航 ---------- */
.admin-nav {
  width: 216px;
  flex: 0 0 216px;
  background-color: var(--pc-nav);
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255, 255, 255, 0.04);
}
.admin-nav__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 18px 14px;
}
.admin-nav__logo {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: var(--pc-gradient-brand);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}
.admin-nav__brand-name {
  color: #e4e9ee;
  font-weight: 700;
  font-size: 15px;
  letter-spacing: 1px;
}
.admin-nav__brand-sub {
  color: #5f6b76;
  font-size: 10px;
  letter-spacing: 0.5px;
}
.admin-nav__menu {
  flex: 1;
  border-right: none;
  padding: 6px 8px;
  overflow-y: auto;
}
.admin-nav__menu :deep(.el-menu-item) {
  height: 44px;
  border-radius: var(--pc-radius);
  margin-bottom: 4px;
  font-size: 13px;
}
.admin-nav__menu :deep(.el-menu-item.is-active) {
  background-color: rgba(43, 164, 113, 0.14);
}
.admin-nav__icon {
  margin-right: 10px;
  font-size: 15px;
}
.admin-nav__badge {
  margin-left: auto;
}
.admin-nav__foot {
  padding: 12px 18px;
  color: #4d5860;
  font-size: 11px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}

/* ---------- 主区 ---------- */
.admin-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.admin-topbar {
  height: 52px;
  flex: 0 0 52px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  background-color: var(--pc-panel);
  border-bottom: 1px solid var(--pc-border);
}
.admin-topbar__title {
  font: var(--pc-font-title);
  color: var(--pc-text);
}
.admin-topbar__right {
  display: flex;
  align-items: center;
  gap: 14px;
}
.admin-topbar__live {
  font-size: 12px;
  color: var(--pc-text-muted);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.admin-topbar__live.is-on {
  color: var(--pc-primary);
}
.admin-topbar__dot {
  display: none;
}
.admin-topbar__user {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--pc-text);
  outline: none;
}
.admin-topbar__avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--pc-primary-soft);
  color: var(--pc-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
}
.admin-topbar__name {
  font-size: 13px;
}

.admin-workspace {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 20px 24px;
}
</style>
