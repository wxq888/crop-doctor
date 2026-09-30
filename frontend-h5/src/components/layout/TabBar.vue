<template>
  <van-tabbar route class="cd-tabbar" :z-index="100" safe-area-inset-bottom>
    <van-tabbar-item to="/home" icon="wap-home-o">首页</van-tabbar-item>
    <van-tabbar-item to="/records" icon="records">记录</van-tabbar-item>
    <!-- 中间凸出「问诊」大圆按钮（ui-design.md §3.1） -->
    <van-tabbar-item to="/chat" class="cd-tabbar__center">
      <template #icon="slotProps">
        <div class="cd-tabbar__bump" :class="{ 'cd-tabbar__bump--active': slotProps.active }">
          <van-icon name="chat-o" />
        </div>
      </template>
      问诊
    </van-tabbar-item>
    <van-tabbar-item to="/knowledge" icon="bookmark-o">知识库</van-tabbar-item>
    <van-tabbar-item to="/mine" icon="user-o">
      我的
      <template #icon>
        <van-badge :dot="badgeStore.hasUnread">
          <van-icon name="user-o" />
        </van-badge>
      </template>
    </van-tabbar-item>
  </van-tabbar>
</template>

<script setup>
import { onMounted } from 'vue'

import { useBadgeStore } from '@/stores/badge'
import { useUserStore } from '@/stores/user'

/**
 * 底部 5 个一级 Tab：首页 · 记录 · ✚问诊(凸出) · 知识库 · 我的。
 * route 模式：选中态由当前路由驱动；「我的」图标挂未读红点。
 */
const badgeStore = useBadgeStore()
const userStore = useUserStore()

onMounted(() => {
  // 已登录时拉一次未读角标（登录/登出切换由各业务页触发 refresh/reset）
  if (userStore.isLoggedIn) {
    badgeStore.refresh()
  }
})
</script>

<style scoped>
.cd-tabbar {
  --van-tabbar-item-active-color: var(--color-primary);
  height: 50px;
}

.cd-tabbar :deep(.van-tabbar-item__icon) {
  font-size: 22px;
}

.cd-tabbar :deep(.van-tabbar-item__text) {
  font-size: 11px;
}

/* 中间凸出按钮：圆形品牌绿底 + 阴影浮起 */
.cd-tabbar :deep(.cd-tabbar__center .van-tabbar-item__icon) {
  font-size: inherit;
}

.cd-tabbar__bump {
  width: 48px;
  height: 48px;
  margin-top: -22px;
  border-radius: 50%;
  background: var(--gradient-brand-135);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
  box-shadow: var(--shadow-primary);
  transition: transform 0.15s ease;
}

.cd-tabbar__bump:active {
  transform: scale(0.94);
}

/* 选中态：整体加深一点，保持凸出（圆形本身已是品牌绿） */
.cd-tabbar__bump--active {
  background: var(--color-primary-dark);
}
</style>
