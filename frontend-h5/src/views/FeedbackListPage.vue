<template>
  <div class="cd-page cd-fbs">
    <PageNav title="我的反馈" />

    <div class="cd-page__body">
      <van-pull-refresh v-model="refreshing" class="cd-fbs__refresh" @refresh="onRefresh">
        <van-list
          v-model:loading="loading"
          :finished="finished"
          finished-text="没有更多了"
          loading-text="加载中…"
          @load="onLoad"
        >
          <div v-for="it in items" :key="it.id" class="cd-fb-item" @click="router.push(`/feedbacks/${it.id}`)">
            <div class="cd-fb-item__top">
              <span class="cd-fb-item__type" :class="`cd-fb-item__type--${it.type}`">
                {{ typeLabel(it.type) }}
              </span>
              <span class="cd-fb-item__title">{{ it.title }}</span>
            </div>
            <div class="cd-fb-item__bottom">
              <span class="cd-fb-item__status" :class="`cd-fb-item__status--${it.status}`">
                {{ statusLabel(it.status) }}
              </span>
              <span v-if="it.unread_count > 0" class="cd-fb-item__unread">💬 {{ it.unread_count }} 条新回复</span>
              <span class="cd-fb-item__time">{{ formatDateTime(it.last_reply_at || it.created_at) }}</span>
              <van-icon name="arrow" class="cd-fb-item__arrow" />
            </div>
          </div>
        </van-list>

        <van-loading v-if="loading && !items.length" class="cd-fbs__loading">加载中…</van-loading>

        <EmptyState
          v-if="finished && !items.length && !loading"
          icon="💬"
          title="还没有反馈记录"
          hint="对检测结果有疑问？在检测详情页点「结果对吗？反馈」告诉我们"
          action-text="去检测"
          @action="router.replace('/home')"
        />
      </van-pull-refresh>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import EmptyState from '@/components/common/EmptyState.vue'
import PageNav from '@/components/common/PageNav.vue'
import * as feedbackApi from '@/api/feedback'
import { useBadgeStore } from '@/stores/badge'
import { formatDateTime } from '@/utils/format'

/**
 * 我的反馈列表：GET /feedback/mine；新回复标（unread_count）。
 */
const router = useRouter()
const badgeStore = useBadgeStore()

const items = ref([])
const page = ref(1)
const PAGE_SIZE = 10
const loading = ref(false)
const finished = ref(false)
const refreshing = ref(false)

function typeLabel(t) {
  return t === 'result_verdict' ? '结果反馈' : '问题咨询'
}

function statusLabel(s) {
  if (s === 'pending') return '待回复'
  if (s === 'replied') return '已回复'
  if (s === 'closed') return '已关闭'
  return s
}

function onRefresh() {
  page.value = 1
  items.value = []
  finished.value = false
  loading.value = true
  onLoad()
}

async function onLoad() {
  try {
    const res = await feedbackApi.listMyFeedbacks({ page: page.value, page_size: PAGE_SIZE })
    const list = (res && res.items) || []
    items.value.push(...list)
    loading.value = false
    refreshing.value = false
    badgeStore.refresh()
    if (!list.length || items.value.length >= ((res && res.total) || 0)) {
      finished.value = true
    } else {
      page.value += 1
    }
  } catch (e) {
    loading.value = false
    refreshing.value = false
    finished.value = true
  }
}
</script>

<style scoped>
.cd-fbs {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + 底部留白（防固定元素遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

.cd-fbs__refresh {
  min-height: 100%;
}

.cd-fbs__loading {
  display: flex;
  justify-content: center;
  padding: 40px 0;
  color: var(--color-text-muted);
}

.cd-fb-item {
  margin: 10px 12px 0;
  padding: 12px;
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.cd-fb-item:last-child {
  margin-bottom: 12px;
}

.cd-fb-item__top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cd-fb-item__type {
  flex: 0 0 auto;
  padding: 2px 8px;
  border-radius: var(--radius-button);
  font: var(--font-mini);
  font-weight: 600;
}

.cd-fb-item__type--result_verdict {
  color: var(--severity-2);
  background: rgba(245, 166, 35, 0.12);
}

.cd-fb-item__type--question {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.cd-fb-item__title {
  flex: 1;
  min-width: 0;
  font: var(--font-body);
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-fb-item__bottom {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  font: var(--font-mini);
}

.cd-fb-item__status {
  padding: 1px 8px;
  border-radius: var(--radius-button);
}

.cd-fb-item__status--pending {
  color: var(--severity-2);
  background: rgba(245, 166, 35, 0.12);
}

.cd-fb-item__status--replied {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.cd-fb-item__status--closed {
  color: var(--color-text-muted);
  background: var(--color-bg);
}

.cd-fb-item__unread {
  color: var(--severity-3);
  font-weight: 600;
}

.cd-fb-item__time {
  margin-left: auto;
  color: var(--color-text-muted);
}

.cd-fb-item__arrow {
  color: var(--color-text-muted);
  font-size: 13px;
}
</style>
