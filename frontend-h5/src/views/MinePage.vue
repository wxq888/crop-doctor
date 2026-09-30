<template>
  <div class="cd-page cd-mine">
    <div class="cd-page__body">
      <!-- ① 头像卡 -->
      <div class="cd-mine__user">
        <div class="cd-mine__avatar">{{ avatarText }}</div>
        <div class="cd-mine__info">
          <div class="cd-mine__name">{{ userStore.displayName }}</div>
          <div class="cd-mine__role">
            <van-tag :type="userStore.isAdmin ? 'danger' : 'primary'" plain>
              {{ userStore.isAdmin ? '管理员' : '普通用户' }}
            </van-tag>
            <span class="cd-mine__username">@{{ username }}</span>
          </div>
        </div>
        <div class="cd-mine__count">
          <b>{{ detectionCount }}</b>
          <span>检测次数</span>
        </div>
      </div>

      <!-- ② 功能列表（含未读角标） -->
      <van-cell-group class="cd-mine__group" :border="false">
        <van-cell title="我的检测记录" icon="photo-o" is-link to="/records" />
        <van-cell title="我的反馈" icon="chat-o" is-link to="/feedbacks">
          <template #title>
            <van-badge :content="badgeStore.feedbackUnread" :show-zero="false" max="99">
              <span class="cd-mine__cell-text">我的反馈</span>
            </van-badge>
          </template>
        </van-cell>
        <van-cell title="预警消息" icon="bell" is-link to="/alerts">
          <template #title>
            <van-badge :content="badgeStore.warningUnread" :show-zero="false" max="99">
              <span class="cd-mine__cell-text">预警消息</span>
            </van-badge>
          </template>
        </van-cell>
        <van-cell title="设置" icon="setting-o" is-link to="/settings" />
        <van-cell title="关于" icon="info-o" is-link to="/about" />
      </van-cell-group>

      <!-- ③ 退出登录 -->
      <div class="cd-mine__logout">
        <van-button block round plain type="danger" class="cd-mine__logout-btn" @click="onLogout">
          退出登录
        </van-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'

import * as detectionApi from '@/api/detection'
import { useUserStore } from '@/stores/user'
import { useChatStore } from '@/stores/chat'
import { useBadgeStore } from '@/stores/badge'

/**
 * 我的 Tab（ui-design.md §3.2 ④）：
 * 头像卡（昵称 + 身份 + 检测次数）→ 功能列表（角标）→ 退出登录。
 */
const router = useRouter()
const userStore = useUserStore()
const chatStore = useChatStore()
const badgeStore = useBadgeStore()

const detectionCount = ref(0)

const avatarText = computed(() => {
  const name = userStore.displayName || '农'
  return name.slice(0, 1)
})

const username = computed(() => (userStore.user && userStore.user.username) || '')

onMounted(async () => {
  // 刷新资料 + 检测次数 + 未读角标
  try {
    await userStore.loadProfile()
  } catch (e) {
    /* 拦截器已处理 */
  }
  try {
    const page = await detectionApi.listDetectionRecords({ page: 1, page_size: 1 })
    detectionCount.value = (page && page.total) || 0
  } catch (e) {
    detectionCount.value = 0
  }
  badgeStore.refresh()
})

/** 退出登录：二次确认 → 清空本地状态 → 回登录页 */
async function onLogout() {
  try {
    await showConfirmDialog({ title: '退出登录', message: '确定要退出当前账号吗？' })
  } catch (e) {
    return
  }
  userStore.logout()
  chatStore.reset()
  badgeStore.reset()
  showToast('已退出登录')
  router.replace('/login')
}
</script>

<style scoped>
.cd-mine {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + TabBar 底部留白（防遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

/* 头像卡 */
.cd-mine__user {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 14px 12px 16px;
  padding: var(--space-16);
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.cd-mine__avatar {
  flex: 0 0 auto;
  width: 60px;
  height: 60px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 26px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cd-mine__info {
  flex: 1;
  min-width: 0;
}

.cd-mine__name {
  font: var(--font-h2);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-mine__role {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.cd-mine__username {
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-mine__count {
  flex: 0 0 auto;
  text-align: center;
}

.cd-mine__count b {
  display: block;
  font-size: 22px;
  font-weight: 600;
  color: var(--color-primary);
}

.cd-mine__count span {
  font: var(--font-mini);
  color: var(--color-text-muted);
}

/* 功能列表 */
.cd-mine__group {
  margin: 0 12px;
  border-radius: var(--radius-card);
  overflow: hidden;
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.cd-mine__group :deep(.van-cell) {
  font-size: 15px;
  padding: 15px 16px;
}

.cd-mine__group :deep(.van-cell__left-icon) {
  color: var(--color-primary);
  font-size: 19px;
  margin-right: 10px;
}

.cd-mine__cell-text {
  font-size: 15px;
}

/* 退出登录 */
.cd-mine__logout {
  margin: 24px 12px;
}

.cd-mine__logout-btn {
  height: 44px;
  border-radius: var(--radius-button);
  font-size: 15px;
}
</style>
