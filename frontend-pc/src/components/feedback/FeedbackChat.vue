<script setup>
/**
 * 工单对话区（ui-design.md §4.3 ⑥）。
 * 用户消息左灰 / 管理员回复右绿；底部回复输入框；已关闭工单禁止回复。
 */
import { computed, nextTick, ref, watch } from 'vue'

import SampleViewer from './SampleViewer.vue'

const props = defineProps({
  /** 工单详情 FeedbackDetail（含 messages[] / record / status / title / user） */
  detail: { type: Object, default: null },
  /** 详情加载中 */
  loading: { type: Boolean, default: false },
  /** 回复提交中 */
  sending: { type: Boolean, default: false },
})

const emit = defineEmits(['reply', 'close'])

const content = ref('')
const listEl = ref(null)

/** 是否已关闭（终态，不可回复） */
const isClosed = computed(() => props.detail && props.detail.status === 'closed')

/** 状态文案 */
const STATUS_TEXT = { pending: '待回复', replied: '已回复', closed: '已关闭' }
const statusText = computed(() => (props.detail ? STATUS_TEXT[props.detail.status] || props.detail.status : ''))

/** 消息列表（升序，用户左侧） */
const messages = computed(() => (props.detail && props.detail.messages) || [])

/** 用户展示名 */
const userName = computed(() => {
  const u = props.detail && props.detail.user
  if (props.detail && props.detail.username) return props.detail.username
  if (u) return u.nickname || u.username || `用户#${u.id}`
  return '用户'
})

/** 发送回复 */
function submit() {
  const text = content.value.trim()
  if (!text || isClosed.value) return
  emit('reply', text)
}

/** 父组件发送成功后调用以清空输入 */
function clearInput() {
  content.value = ''
}

defineExpose({ clearInput })

/** 切换工单 / 新消息 → 滚动到底部 */
watch(
  () => [props.detail && props.detail.id, messages.value.length],
  () => {
    nextTick(() => {
      if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
    })
  },
)
</script>

<template>
  <div class="fb-chat">
    <!-- 空态 -->
    <div v-if="!detail && !loading" class="fb-chat__empty">
      <span class="fb-chat__empty-icon">💬</span>
      <span>请从左侧选择一条工单</span>
    </div>

    <div v-else-if="loading" class="fb-chat__empty">加载中…</div>

    <template v-else>
      <!-- 头部 -->
      <div class="fb-chat__head">
        <div class="fb-chat__head-main">
          <span class="fb-chat__title">{{ detail.title || '工单' }}</span>
          <el-tag size="small" :type="detail.status === 'closed' ? 'info' : detail.status === 'pending' ? 'warning' : 'success'" effect="plain">
            {{ statusText }}
          </el-tag>
          <el-tag v-if="detail.type" size="small" effect="plain">{{ detail.type === 'result_verdict' ? '结果核对' : '问题咨询' }}</el-tag>
        </div>
        <div class="fb-chat__head-right">
          <span class="fb-chat__user">{{ userName }}</span>
          <el-button v-if="detail.status !== 'closed'" size="small" type="danger" plain @click="emit('close')">
            关闭工单
          </el-button>
        </div>
      </div>

      <!-- 样本（检测反馈类） -->
      <div v-if="detail.record" class="fb-chat__sample">
        <SampleViewer :record="detail.record" />
      </div>

      <!-- 对话区 -->
      <div ref="listEl" class="fb-chat__list">
        <div
          v-for="(m, i) in messages"
          :key="m.id ?? i"
          class="fb-bubble"
          :class="m.sender_role === 'admin' ? 'fb-bubble--admin' : 'fb-bubble--user'"
        >
          <div class="fb-bubble__meta">
            <span class="fb-bubble__who">{{ m.sender_role === 'admin' ? '管理员' : userName }}</span>
            <span class="fb-bubble__time cd-mono">{{ (m.created_at || '').replace('T', ' ').slice(0, 16) }}</span>
          </div>
          <div class="fb-bubble__content">{{ m.content }}</div>
        </div>
        <div v-if="!messages.length" class="fb-chat__no-msg">暂无消息</div>
      </div>

      <!-- 回复输入 -->
      <div class="fb-chat__input">
        <el-input
          v-model="content"
          type="textarea"
          :rows="3"
          resize="none"
          :disabled="isClosed"
          :placeholder="isClosed ? '工单已关闭，无法回复' : '输入回复内容，回车换行，点击发送'"
        />
        <div class="fb-chat__input-foot">
          <span class="fb-chat__hint">{{ isClosed ? '该工单已关闭（终态）' : '回复将即时同步给用户' }}</span>
          <el-button type="primary" :loading="sending" :disabled="isClosed || !content.trim()" @click="submit">
            发送回复
          </el-button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.fb-chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.fb-chat__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--pc-text-muted);
  font-size: 13px;
}
.fb-chat__empty-icon {
  font-size: 30px;
  opacity: 0.6;
}
.fb-chat__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--pc-border);
}
.fb-chat__head-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.fb-chat__title {
  font-weight: 600;
  color: var(--pc-text);
  font-size: 14px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}
.fb-chat__head-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.fb-chat__user {
  font-size: 12px;
  color: var(--pc-text-muted);
}
.fb-chat__sample {
  margin-top: 10px;
}
.fb-chat__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 4px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.fb-chat__no-msg {
  text-align: center;
  color: var(--pc-text-muted);
  font-size: 12px;
  margin-top: 20px;
}
.fb-bubble {
  max-width: 76%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.fb-bubble--user {
  align-self: flex-start;
}
.fb-bubble--admin {
  align-self: flex-end;
  align-items: flex-end;
}
.fb-bubble__meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--pc-text-muted);
}
.fb-bubble__content {
  padding: 9px 12px;
  border-radius: 10px;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
  white-space: pre-wrap;
}
.fb-bubble--user .fb-bubble__content {
  background: var(--pc-border);
  color: var(--pc-text);
  border-top-left-radius: 3px;
}
.fb-bubble--admin .fb-bubble__content {
  background: var(--pc-primary-soft);
  color: var(--pc-text);
  border-top-right-radius: 3px;
}
.fb-chat__input {
  border-top: 1px solid var(--pc-border);
  padding-top: 10px;
}
.fb-chat__input-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
.fb-chat__hint {
  font-size: 11px;
  color: var(--pc-text-muted);
}
</style>
