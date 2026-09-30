<template>
  <div class="cd-page cd-records">
    <!-- 顶部：标题 + 筛选（按病害 / 时间） -->
    <header class="cd-records__head">
      <div class="cd-records__title">检测记录</div>
      <van-search
        v-model="diseaseKw"
        class="cd-records__search"
        placeholder="按病害名称搜索"
        shape="round"
        @search="applyFilter"
        @clear="applyFilter"
      />
      <div class="cd-records__dates">
        <span class="cd-records__date" @click="showStart = true">
          📅 {{ start ? formatDate(start) : '开始日期' }}
        </span>
        <span class="cd-records__dash">至</span>
        <span class="cd-records__date" @click="showEnd = true">
          {{ end ? formatDate(end) : '结束日期' }}
        </span>
        <span v-if="start || end" class="cd-records__clear" @click="clearDates">清除</span>
      </div>
    </header>

    <!-- 列表：下拉刷新 + 上拉加载 -->
    <div class="cd-page__body">
      <van-pull-refresh v-model="refreshing" class="cd-records__refresh" @refresh="onRefresh">
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
            class="cd-record-item"
            @click="router.push(`/detection/${it.id}`)"
          >
            <img class="cd-record-item__thumb" :src="resolveStaticUrl(it.thumb_url)" alt="检测缩略图" />
            <div class="cd-record-item__main">
              <div class="cd-record-item__name">{{ it.disease_cn || it.top_disease || '未知病害' }}</div>
              <div class="cd-record-item__time">{{ formatDateTime(it.created_at) }}</div>
            </div>
            <SeverityTag
              :level="it.is_healthy ? 0 : it.severity_level"
              :label="it.is_healthy ? '健康' : it.severity_label"
              :color="it.is_healthy ? HEALTHY_COLOR : ''"
            />
            <van-icon name="arrow" class="cd-record-item__arrow" />
          </div>
        </van-list>

        <EmptyState
          v-if="finished && !items.length && !loading"
          icon="🧪"
          title="还没有检测记录"
          hint="拍一张叶片照片，AI 立刻帮你识别病害"
          action-text="去检测"
          @action="router.replace('/home')"
        />
      </van-pull-refresh>
    </div>

    <van-calendar
      v-model:show="showStart"
      title="选择开始日期"
      :min-date="minDate"
      :max-date="maxDate"
      @confirm="onStartConfirm"
    />
    <van-calendar
      v-model:show="showEnd"
      title="选择结束日期"
      :min-date="minDate"
      :max-date="maxDate"
      @confirm="onEndConfirm"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import EmptyState from '@/components/common/EmptyState.vue'
import SeverityTag from '@/components/common/SeverityTag.vue'
import * as detectionApi from '@/api/detection'
import { resolveStaticUrl } from '@/api/chat'
import { HEALTHY_COLOR } from '@/stores/chat'
import { formatDate, formatDateTime } from '@/utils/format'

/**
 * 记录 Tab（ui-design.md §3.2 ⑤）：
 * 缩略图 + 病害名 + 分级标签 + 时间；按病害/时间筛选；分页加载。
 */
const router = useRouter()

const diseaseKw = ref('')
const start = ref(null)
const end = ref(null)
const showStart = ref(false)
const showEnd = ref(false)

const items = ref([])
const page = ref(1)
const PAGE_SIZE = 10
const loading = ref(false)
const finished = ref(false)
const refreshing = ref(false)

// 日历可选范围：近两年 ~ 今天
const now = new Date()
const minDate = new Date(now.getFullYear() - 2, 0, 1)
const maxDate = now

function onStartConfirm(d) {
  start.value = d
  showStart.value = false
  applyFilter()
}

function onEndConfirm(d) {
  end.value = d
  showEnd.value = false
  applyFilter()
}

function clearDates() {
  start.value = null
  end.value = null
  applyFilter()
}

/** 筛选条件变化：重置后重新加载 */
function applyFilter() {
  page.value = 1
  items.value = []
  finished.value = false
  // 若列表当前空闲则手动触发一次；否则让 van-list 的下一轮 onLoad 接管
  if (!loading.value) {
    loading.value = true
    onLoad()
  }
}

/** 下拉刷新 */
function onRefresh() {
  page.value = 1
  items.value = []
  finished.value = false
  loading.value = true
  onLoad()
}

/** 上拉加载一页 */
async function onLoad() {
  try {
    const params = { page: page.value, page_size: PAGE_SIZE }
    const kw = diseaseKw.value.trim()
    if (kw) params.disease = kw
    if (start.value) params.start = formatDate(start.value)
    if (end.value) params.end = formatDate(end.value)

    const res = await detectionApi.listDetectionRecords(params)
    const list = (res && res.items) || []
    items.value.push(...list)
    loading.value = false
    refreshing.value = false

    if (!list.length || items.value.length >= (res && res.total) || 0) {
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
.cd-records {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + TabBar 底部留白（防遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

.cd-records__head {
  flex: 0 0 auto;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  padding-top: env(safe-area-inset-top);
}

.cd-records__title {
  font: var(--font-h2);
  color: var(--color-text);
  padding: 14px 16px 0;
}

.cd-records__search {
  background: transparent;
}

.cd-records__search :deep(.van-search__content) {
  background: var(--color-bg);
  border-radius: var(--radius-button);
}

.cd-records__search :deep(.van-field__control) {
  font: var(--font-body);
}

/* 日期筛选行 */
.cd-records__dates {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px 10px;
  font: var(--font-mini);
}

.cd-records__date {
  color: var(--color-primary);
  background: var(--color-primary-soft);
  border-radius: var(--radius-button);
  padding: 4px 12px;
  font-weight: 600;
}

.cd-records__dash {
  color: var(--color-text-muted);
}

.cd-records__clear {
  margin-left: auto;
  color: var(--color-text-muted);
  padding: 4px 6px;
}

.cd-records__refresh {
  min-height: 100%;
}

/* 列表项 */
.cd-record-item {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 10px 12px 0;
  padding: var(--space-12);
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.cd-record-item:last-child {
  margin-bottom: 12px;
}

.cd-record-item__thumb {
  flex: 0 0 auto;
  width: 60px;
  height: 60px;
  border-radius: 10px;
  object-fit: cover;
  background: var(--color-bg);
}

.cd-record-item__main {
  flex: 1;
  min-width: 0;
}

.cd-record-item__name {
  font: var(--font-body);
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-record-item__time {
  margin-top: 4px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-record-item__arrow {
  flex: 0 0 auto;
  color: var(--color-text-muted);
  font-size: 14px;
}
</style>
