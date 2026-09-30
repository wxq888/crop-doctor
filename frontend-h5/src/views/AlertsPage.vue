<template>
  <div class="cd-page cd-alerts">
    <PageNav title="预警消息" />

    <div class="cd-page__body">
      <van-pull-refresh v-model="refreshing" class="cd-alerts__refresh" @refresh="onRefresh">
        <van-list
          v-model:loading="loading"
          :finished="finished"
          finished-text="没有更多了"
          loading-text="加载中…"
          @load="onLoad"
        >
          <div
            v-for="it in items"
            :key="it.id"
            class="cd-alert-item"
            :class="{ 'cd-alert-item--unread': !it.is_read }"
            @click="onRead(it)"
          >
            <div class="cd-alert-item__top">
              <span class="cd-alert-item__risk" :style="riskStyle(it.risk_level)">
                {{ riskLabel(it.risk_level) }}
              </span>
              <span class="cd-alert-item__disease">{{ it.disease_cn || it.disease }}</span>
              <span class="cd-alert-item__time">{{ formatDateTime(it.created_at) }}</span>
            </div>
            <p class="cd-alert-item__content">{{ it.content }}</p>
            <div v-if="it.location || it.forecast_date" class="cd-alert-item__meta">
              <span v-if="it.location">📍 {{ it.location }}</span>
              <span v-if="it.forecast_date">预报日 {{ it.forecast_date }}</span>
            </div>
            <i v-if="!it.is_read" class="cd-alert-item__dot"></i>
          </div>
        </van-list>

        <van-loading v-if="loading && !items.length" class="cd-alerts__loading">加载中…</van-loading>

        <EmptyState
          v-if="finished && !items.length && !loading"
          icon="🔔"
          title="暂无预警消息"
          hint="当天气条件满足病害爆发风险时，预警会第一时间推送到这里"
          action-text="返回首页"
          @action="router.replace('/home')"
        />
      </van-pull-refresh>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'

import EmptyState from '@/components/common/EmptyState.vue'
import PageNav from '@/components/common/PageNav.vue'
import * as warningApi from '@/api/warning'
import { SEVERITY_COLORS } from '@/stores/chat'
import { useBadgeStore } from '@/stores/badge'
import { formatDateTime } from '@/utils/format'
import alertsWs from '@/utils/alertsWs'

/**
 * 预警消息页：列表 + 点击已读（同时刷新角标）。
 * 风险等级语义色：high→红 / mid→琥珀 / low→绿（§2.1，且始终带文字）。
 * 同时订阅预警实时流：收到新预警时插入列表顶部（去重）；轮询 / 下拉刷新仍为兜底。
 */
const router = useRouter()
const badgeStore = useBadgeStore()

const items = ref([])
const page = ref(1)
const PAGE_SIZE = 10
const loading = ref(false)
const finished = ref(false)
const refreshing = ref(false)

/** 取消实时预警订阅（卸载时调用，避免重复订阅） */
let unsubscribeAlert = null

onMounted(() => {
  unsubscribeAlert = alertsWs.subscribe(onRealtimeAlert)
})

onUnmounted(() => {
  if (unsubscribeAlert) {
    unsubscribeAlert()
    unsubscribeAlert = null
  }
})

/** 收到实时预警：去重后插入列表顶部 */
function onRealtimeAlert(data) {
  if (!data || data.id == null) return
  if (items.value.some((it) => it.id === data.id)) return
  items.value.unshift({
    id: data.id,
    source: data.source,
    disease: data.disease,
    disease_cn: data.disease_cn,
    risk_level: data.risk_level,
    content: data.content,
    location: data.location,
    forecast_date: data.forecast_date,
    is_read: false,
    for_me: true,
    created_at: data.created_at,
  })
}

const RISK_LABELS = { high: '高风险', mid: '中风险', low: '低风险' }
const RISK_COLORS = { high: SEVERITY_COLORS[3], mid: SEVERITY_COLORS[2], low: SEVERITY_COLORS[1] }

function riskLabel(level) {
  return RISK_LABELS[level] || '风险'
}

function riskStyle(level) {
  const color = RISK_COLORS[level] || SEVERITY_COLORS[2]
  return { color, backgroundColor: `${color}1f`, borderColor: color }
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
    const res = await warningApi.listAlerts({ page: page.value, page_size: PAGE_SIZE })
    const list = (res && res.items) || []
    items.value.push(...list)
    loading.value = false
    refreshing.value = false
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

/** 点击：未读则置已读并刷新角标 */
async function onRead(it) {
  if (it.is_read) return
  try {
    await warningApi.markAlertRead(it.id)
    it.is_read = true
    badgeStore.refresh()
  } catch (e) {
    showToast('标记已读失败，请重试')
  }
}
</script>

<style scoped>
.cd-alerts {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + 底部留白（防固定元素遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

.cd-alerts__refresh {
  min-height: 100%;
}

.cd-alerts__loading {
  display: flex;
  justify-content: center;
  padding: 40px 0;
  color: var(--color-text-muted);
}

.cd-alert-item {
  position: relative;
  margin: 10px 12px 0;
  padding: 12px;
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  border-left: 4px solid var(--severity-2);
}

.cd-alert-item:last-child {
  margin-bottom: 12px;
}

.cd-alert-item__top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cd-alert-item__risk {
  flex: 0 0 auto;
  padding: 2px 8px;
  border-radius: var(--radius-button);
  border: 1px solid transparent;
  font: var(--font-mini);
  font-weight: 600;
}

.cd-alert-item__disease {
  flex: 1;
  min-width: 0;
  font: var(--font-body);
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-alert-item__time {
  flex: 0 0 auto;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-alert-item__content {
  margin: 8px 0 0;
  font: var(--font-caption);
  color: var(--color-text-muted);
  line-height: 1.6;
}

.cd-alert-item__meta {
  display: flex;
  gap: 12px;
  margin-top: 8px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

/* 未读红点（右上角） */
.cd-alert-item__dot {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--severity-3);
}

.cd-alert-item--unread {
  background: #fffdf6;
}
</style>
