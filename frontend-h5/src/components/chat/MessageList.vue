<template>
  <!-- 消息滚动容器：自动滚底 + 空态引导 -->
  <div ref="listRef" class="cd-msg-list">
    <!-- 空状态：引导 + 快捷问题 -->
    <div v-if="!messages.length" class="cd-empty">
      <div class="cd-empty__icon">🌿</div>
      <p class="cd-empty__title">我是作物医生助手</p>
      <p class="cd-empty__desc">
        拍照识病害 · AI 帮你看田<br />
        有什么种植问题，尽管问我～
      </p>
      <QuickQuestions :questions="quickQuestions" @select="$emit('quick', $event)" />
    </div>

    <template v-else>
      <MessageBubble v-for="m in messages" :key="m.id" :message="m" />
      <div class="cd-msg-list__pad"></div>
    </template>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'

import MessageBubble from './MessageBubble.vue'
import QuickQuestions from './QuickQuestions.vue'

const props = defineProps({
  /** 消息列表 */
  messages: {
    type: Array,
    default: () => [],
  },
  /** 快捷问题 */
  quickQuestions: {
    type: Array,
    default: () => [],
  },
  /** 是否流式中（用于触发滚动） */
  streaming: {
    type: Boolean,
    default: false,
  },
})

defineEmits(['quick'])

const listRef = ref(null)

/** 滚到底部 */
async function scrollToBottom() {
  await nextTick()
  const el = listRef.value
  if (el) {
    el.scrollTop = el.scrollHeight
  }
}

// 消息条数变化（新增气泡）时滚底
watch(
  () => props.messages.length,
  () => scrollToBottom(),
)

// 流式增量：监听最后一条消息内容长度变化，持续滚底
watch(
  () => {
    const last = props.messages[props.messages.length - 1]
    return last ? last.content.length : 0
  },
  () => {
    if (props.streaming) scrollToBottom()
  },
)

// 流式结束也滚一次
watch(
  () => props.streaming,
  (val) => {
    if (!val) scrollToBottom()
  },
)

defineExpose({ scrollToBottom })
</script>

<style scoped>
.cd-msg-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
  padding-top: 8px;
}

.cd-msg-list__pad {
  height: 8px;
}

.cd-empty {
  height: 100%;
  min-height: 320px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px 20px;
  text-align: center;
}

.cd-empty__icon {
  width: 84px;
  height: 84px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 42px;
}

.cd-empty__title {
  margin: 4px 0 0;
  font: var(--font-h1);
  color: var(--color-text);
}

.cd-empty__desc {
  margin: 0 0 12px;
  font: var(--font-caption);
  color: var(--color-text-muted);
  line-height: 1.7;
}
</style>
