<template>
  <div class="cd-page cd-fbd">
    <PageNav title="反馈详情" />

    <!-- 工单对话区 -->
    <div ref="scrollBox" class="cd-page__body cd-fbd__thread">
      <van-loading v-if="loading" class="cd-fbd__loading">加载中…</van-loading>

      <EmptyState
        v-else-if="!detail"
        icon="💬"
        title="工单不存在或已删除"
        action-text="返回我的反馈"
        @action="router.replace('/feedbacks')"
      />

      <template v-else>
        <!-- 工单头信息 -->
        <div class="cd-fbd__head">
          <div class="cd-fbd__title">{{ detail.title }}</div>
          <div class="cd-fbd__meta">
            <span class="cd-fbd__status" :class="`cd-fbd__status--${detail.status}`">{{ statusLabel(detail.status) }}</span>
            <span v-if="detail.type === 'result_verdict' && detail.verdict" class="cd-fbd__verdict">
              判定：{{ verdictLabel(detail.verdict) }}
            </span>
            <span v-if="detail.correct_disease" class="cd-fbd__correct">正确病害：{{ detail.correct_disease }}</span>
          </div>
          <!-- 关联检测样本 -->
          <div v-if="detail.record && sampleThumb" class="cd-fbd__sample" @click="goRecord">
            <img class="cd-fbd__sample-img" :src="sampleThumb" alt="关联检测样本" />
            <div class="cd-fbd__sample-main">
              <div class="cd-fbd__sample-title">关联检测样本</div>
              <div class="cd-fbd__sample-sub">{{ detail.record.top_disease || '未知病害' }} · 点击查看详情</div>
            </div>
            <van-icon name="arrow" class="cd-fbd__sample-arrow" />
          </div>
        </div>

        <!-- 多轮往来消息：管理员左（白）/ 用户右（绿，对齐问诊气泡习惯） -->
        <div
          v-for="m in detail.messages"
          :key="m.id"
          class="cd-fbd__msg"
          :class="m.sender_role === 'user' ? 'cd-fbd__msg--me' : 'cd-fbd__msg--admin'"
        >
          <div class="cd-fbd__role">
            {{ m.sender_role === 'user' ? '我' : '客服' }}
          </div>
          <div class="cd-fbd__bubble">{{ m.content }}</div>
          <div class="cd-fbd__time">{{ formatDateTime(m.created_at) }}</div>
        </div>
      </template>
    </div>

    <!-- 底部追问输入栏（closed 终态不可回复 → 6002 由后端拦截，前端直接禁用） -->
    <div class="cd-fbd__input">
      <template v-if="detail && detail.status === 'closed'">
        <span class="cd-fbd__closed">工单已关闭，感谢你的反馈</span>
      </template>
      <template v-else>
        <van-field
          v-model="draft"
          class="cd-fbd__field"
          type="textarea"
          rows="1"
          autosize
          maxlength="500"
          placeholder="继续追问…"
        />
        <van-button round type="primary" class="cd-fbd__send" :loading="sending" @click="onSend">
          发送
        </van-button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'

import EmptyState from '@/components/common/EmptyState.vue'
import PageNav from '@/components/common/PageNav.vue'
import * as feedbackApi from '@/api/feedback'
import { resolveStaticUrl } from '@/api/chat'
import { useBadgeStore } from '@/stores/badge'
import { formatDateTime } from '@/utils/format'

/**
 * 反馈详情页：工单头 + 关联样本 + 多轮往来（GET /feedback/{id} 打开即置已读）
 * + 底部追问输入（POST /feedback/{id}/messages）。
 */
const route = useRoute()
const router = useRouter()
const badgeStore = useBadgeStore()

const detail = ref(null)
const loading = ref(false)
const draft = ref('')
const sending = ref(false)
const scrollBox = ref(null)

const sampleThumb = computed(() =>
  resolveStaticUrl(detail.value && detail.value.record && detail.value.record.thumb_url),
)

function statusLabel(s) {
  if (s === 'pending') return '待回复'
  if (s === 'replied') return '已回复'
  if (s === 'closed') return '已关闭'
  return s
}

function verdictLabel(v) {
  if (v === 'correct') return '正确'
  if (v === 'wrong') return '错误'
  if (v === 'unsure') return '存疑'
  return v
}

async function load(id) {
  const numId = Number(id)
  if (!numId || Number.isNaN(numId)) {
    detail.value = null
    return
  }
  loading.value = true
  try {
    // 打开详情即把 admin 消息置已读（后端行为）→ 同步刷新角标
    detail.value = await feedbackApi.getFeedbackDetail(numId)
    badgeStore.refresh()
    await nextTick()
    scrollToBottom()
  } catch (e) {
    detail.value = null
  } finally {
    loading.value = false
  }
}

function scrollToBottom() {
  const box = scrollBox.value
  if (box) box.scrollTop = box.scrollHeight
  // 页面改为 body 级滚动后容器自身不产生滚动条，用窗口滚动兜底
  window.scrollTo(0, document.body.scrollHeight)
}

function goRecord() {
  if (detail.value && detail.value.record_id) {
    router.push(`/detection/${detail.value.record_id}`)
  }
}

/** 追问发送 */
async function onSend() {
  const content = draft.value.trim()
  if (!content || sending.value) return
  sending.value = true
  try {
    const msg = await feedbackApi.sendFeedbackMessage(detail.value.id, content)
    detail.value.messages.push(msg)
    // 用户追问后工单回到待回复（状态机 §5）
    detail.value.status = 'pending'
    draft.value = ''
    await nextTick()
    scrollToBottom()
  } catch (e) {
    /* 拦截器已提示（含 6002 已关闭） */
  } finally {
    sending.value = false
  }
}

watch(() => route.params.id, load, { immediate: true })
</script>

<style scoped>
.cd-fbd {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + 底部留白（防固定元素遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

.cd-fbd__thread {
  padding-bottom: 12px;
}

.cd-fbd__loading {
  display: flex;
  justify-content: center;
  padding: 48px 0;
  color: var(--color-text-muted);
}

/* 工单头 */
.cd-fbd__head {
  margin: 12px 12px 0;
  padding: var(--space-12);
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.cd-fbd__title {
  font: var(--font-h2);
  color: var(--color-text);
}

.cd-fbd__meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  flex-wrap: wrap;
  font: var(--font-mini);
}

.cd-fbd__status {
  padding: 1px 8px;
  border-radius: var(--radius-button);
}

.cd-fbd__status--pending {
  color: var(--severity-2);
  background: rgba(245, 166, 35, 0.12);
}

.cd-fbd__status--replied {
  color: var(--color-primary);
  background: var(--color-primary-soft);
}

.cd-fbd__status--closed {
  color: var(--color-text-muted);
  background: var(--color-bg);
}

.cd-fbd__verdict,
.cd-fbd__correct {
  color: var(--color-text-muted);
}

/* 关联样本 */
.cd-fbd__sample {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  padding: 8px;
  background: var(--color-bg);
  border-radius: 10px;
}

.cd-fbd__sample-img {
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  border-radius: 8px;
  object-fit: cover;
  background: var(--color-surface);
}

.cd-fbd__sample-main {
  flex: 1;
  min-width: 0;
}

.cd-fbd__sample-title {
  font: var(--font-caption);
  font-weight: 600;
  color: var(--color-text);
}

.cd-fbd__sample-sub {
  margin-top: 2px;
  font: var(--font-mini);
  color: var(--color-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-fbd__sample-arrow {
  color: var(--color-text-muted);
}

/* 消息气泡 */
.cd-fbd__msg {
  margin: 12px 12px 0;
  display: flex;
  flex-direction: column;
  max-width: 82%;
}

.cd-fbd__msg--me {
  align-items: flex-end;
  margin-left: auto;
}

.cd-fbd__msg--admin {
  align-items: flex-start;
}

.cd-fbd__role {
  font: var(--font-mini);
  color: var(--color-text-muted);
  margin-bottom: 4px;
}

.cd-fbd__bubble {
  padding: 10px 12px;
  border-radius: var(--radius-bubble);
  font: var(--font-body);
  color: var(--color-text);
  line-height: 1.6;
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  white-space: pre-wrap;
  word-break: break-word;
}

.cd-fbd__msg--me .cd-fbd__bubble {
  background: var(--color-primary);
  color: #fff;
  border-bottom-right-radius: var(--radius-bubble-tail);
}

.cd-fbd__time {
  margin-top: 4px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

/* 底部输入栏 */
.cd-fbd__input {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 10px 12px;
  padding-bottom: calc(10px + env(safe-area-inset-bottom));
  background: var(--color-surface);
  border-top: 1px solid var(--color-border);
}

.cd-fbd__field {
  flex: 1;
  background: var(--color-bg);
  border-radius: var(--radius-input);
  padding: 8px 12px;
}

.cd-fbd__send {
  flex: 0 0 auto;
  height: 38px;
  padding: 0 18px;
  border-radius: var(--radius-button);
  font-size: 14px;
}

.cd-fbd__closed {
  flex: 1;
  text-align: center;
  font: var(--font-caption);
  color: var(--color-text-muted);
  padding: 6px 0;
}
</style>
