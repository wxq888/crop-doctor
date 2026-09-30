<template>
  <!-- 底部输入栏：圆角输入框 + 圆形发送钮（品牌绿）；流式中转「停止」 -->
  <div class="cd-input-bar">
    <div class="cd-input-bar__field">
      <van-field
        v-model="text"
        class="cd-input-bar__input"
        type="textarea"
        rows="1"
        autosize
        :border="false"
        :disabled="streaming"
        placeholder="描述作物症状，问问作物医生…"
        @keydown.enter.exact.prevent="submit"
      />
    </div>

    <button
      v-if="!streaming"
      class="cd-send-btn"
      :class="{ 'cd-send-btn--disabled': !canSend }"
      :disabled="!canSend"
      @click="submit"
    >
      <van-icon name="arrow-up" />
    </button>
    <button v-else class="cd-send-btn cd-send-btn--stop" @click="$emit('stop')">
      <van-icon name="stop-circle-o" />
    </button>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  /** 是否正在流式接收 */
  streaming: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['send', 'stop'])

const text = ref('')

const canSend = computed(() => !props.streaming && text.value.trim().length > 0)

function submit() {
  if (!canSend.value) return
  const q = text.value.trim()
  text.value = ''
  emit('send', q)
}

/** 供父组件在需要时清空输入（预留） */
function clear() {
  text.value = ''
}

defineExpose({ clear })
</script>

<style scoped>
.cd-input-bar {
  display: flex;
  align-items: flex-end;
  gap: 10px;
  padding: 8px 12px calc(8px + env(safe-area-inset-bottom));
  background: var(--color-surface);
  border-top: 1px solid var(--color-border);
}

.cd-input-bar__field {
  flex: 1;
  min-width: 0;
  background: var(--color-bg);
  border-radius: var(--radius-input);
  padding: 2px 2px;
}

.cd-input-bar__input {
  background: transparent;
  padding: 8px 10px;
  font: var(--font-body);
}

.cd-input-bar__input :deep(.van-field__control) {
  font: var(--font-body);
  color: var(--color-text);
  max-height: 92px;
  line-height: 1.5;
}

.cd-send-btn {
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  border: none;
  border-radius: 50%;
  background: var(--gradient-brand-135);
  color: #fff;
  font-size: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-primary);
  transition: transform 0.15s ease;
}

.cd-send-btn:active {
  transform: scale(0.94);
}

.cd-send-btn--disabled {
  background: #c8d3cc;
  box-shadow: none;
}

.cd-send-btn--stop {
  background: var(--color-text-muted);
  box-shadow: none;
}
</style>
