<template>
  <div class="cd-app" :class="{ 'cd-app--tabbar': !!route.meta.tabbar }">
    <router-view />
  </div>
  <!-- 底部 5 Tab 导航：仅在一级 Tab 页显示（meta.tabbar） -->
  <TabBar v-if="route.meta.tabbar" />
</template>

<script setup>
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import { showNotify } from 'vant'

import TabBar from '@/components/layout/TabBar.vue'
import { useBadgeStore } from '@/stores/badge'
import { useUserStore } from '@/stores/user'
import alertsWs from '@/utils/alertsWs'

/**
 * 根组件：路由出口 + TabBar 容器。
 * cd-app--tabbar 给页面留出底部导航高度，避免内容被遮挡。
 *
 * 预警实时推送：登录后自动连接 WS，登出 / 切到登录页断开；
 * 收到 warning.created → Vant 通知（病害名 + 风险等级 + 建议摘要）+ 刷新未读角标
 * （既有轮询兜底保留在 stores/badge.js）。
 */
const route = useRoute()
const userStore = useUserStore()
const badgeStore = useBadgeStore()

const RISK_LABELS = { high: '高风险', mid: '中风险', low: '低风险' }

/** 收到一条实时预警：弹通知 + 刷新未读角标 */
function onWarning(data) {
  const name = (data && (data.disease_cn || data.disease)) || '作物病害'
  const risk = RISK_LABELS[data && data.risk_level] || '风险'
  showNotify({
    type: data && data.risk_level === 'high' ? 'danger' : 'warning',
    message: `${name} ${risk}预警\n${(data && data.content) || ''}`,
    duration: 5000,
  })
  badgeStore.refresh()
}

// 订阅预警事件（App 仅挂载一次）
alertsWs.subscribe(onWarning)

// 登录态 / 路由变化 → 连接或断开：登录后连接；登出或切到登录页断开
watch(
  () => [userStore.token, route.name],
  () => {
    if (userStore.token && route.name !== 'login') {
      alertsWs.connect(userStore.token)
    } else {
      alertsWs.disconnect()
    }
  },
  { immediate: true },
)
</script>

<style>
.cd-app {
  height: 100%;
}

/* 带 TabBar 的页面：预留底部导航高度（含安全区） */
.cd-app--tabbar {
  box-sizing: border-box;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
}
</style>
