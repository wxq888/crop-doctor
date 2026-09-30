<template>
  <!-- 单个对话气泡：用户右绿 / AI 左白，非对称圆角（发送方右下 4px） -->
  <div class="cd-bubble-row" :class="isUser ? 'cd-bubble-row--user' : 'cd-bubble-row--ai'">
    <div v-if="!isUser" class="cd-bubble-avatar">🌱</div>

    <div class="cd-bubble-wrap">
      <div class="cd-bubble" :class="isUser ? 'cd-bubble--user' : 'cd-bubble--ai'">
        <span class="cd-bubble__text">{{ message.content }}</span>
        <!-- 流式打字光标 -->
        <span v-if="message.streaming" class="cd-cursor">▍</span>
        <!-- 空流式且还没出字时的占位动画 -->
        <span v-if="message.streaming && !message.content" class="cd-bubble__typing">
          <i></i><i></i><i></i>
        </span>
      </div>

      <!-- 引用来源灰条（仅 AI 且存在引用时渲染；流式中只显示一行紧凑摘要） -->
      <CitationBar
        v-if="!isUser && citations.length"
        :citations="citations"
        :streaming="messageStreaming"
      />

      <div class="cd-bubble-time">{{ timeText }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

import CitationBar from './CitationBar.vue'

const props = defineProps({
  /** 消息对象 {id,role,content,citations,created_at,streaming} */
  message: {
    type: Object,
    required: true,
  },
})

const isUser = computed(() => props.message.role === 'user')

const citations = computed(() => props.message.citations || [])

/** 该条消息是否还在流式输出（传给 CitationBar 控制引用区展示形态） */
const messageStreaming = computed(() => !!props.message.streaming)

/** 时间戳只显示 HH:mm，避免 H5 气泡过宽 */
const timeText = computed(() => {
  const raw = props.message.created_at
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return ''
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
})
</script>

<style scoped>
.cd-bubble-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 12px;
}

.cd-bubble-row--user {
  flex-direction: row-reverse;
}

.cd-bubble-avatar {
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  margin-top: 2px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 18px;
  line-height: 34px;
  text-align: center;
}

.cd-bubble-wrap {
  display: flex;
  flex-direction: column;
  max-width: 76%;
  min-width: 0;
}

.cd-bubble-row--user .cd-bubble-wrap {
  align-items: flex-end;
}

.cd-bubble {
  position: relative;
  padding: 10px 12px;
  font: var(--font-body);
  word-break: break-word;
  white-space: pre-wrap;
  box-shadow: var(--shadow-card);
}

/* AI：左侧白底深字，右下角外侧圆角 */
.cd-bubble--ai {
  background: var(--color-surface);
  color: var(--color-text);
  border-radius: var(--radius-bubble) var(--radius-bubble) var(--radius-bubble)
    var(--radius-bubble-tail);
}

/* 用户：右侧品牌绿底白字，右下角外侧圆角（发送方） */
.cd-bubble--user {
  background: var(--color-primary);
  color: #ffffff;
  border-radius: var(--radius-bubble) var(--radius-bubble) var(--radius-bubble-tail)
    var(--radius-bubble);
}

.cd-bubble__text {
  white-space: pre-wrap;
}

/* 等待首字的三点动画 */
.cd-bubble__typing {
  display: inline-flex;
  gap: 3px;
  margin-left: 4px;
  vertical-align: middle;
}

.cd-bubble__typing i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--color-text-muted);
  animation: cd-typing 1.2s infinite ease-in-out;
}

.cd-bubble__typing i:nth-child(2) {
  animation-delay: 0.2s;
}

.cd-bubble__typing i:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes cd-typing {
  0%,
  60%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  30% {
    opacity: 1;
    transform: translateY(-3px);
  }
}

.cd-bubble-time {
  margin-top: 4px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}
</style>
