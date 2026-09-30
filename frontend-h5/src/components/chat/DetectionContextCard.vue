<template>
  <!-- 检测上下文卡片：缩略图 + 作物·病害 H1 + 分级标签（语义色）+ 置信度；可关闭 -->
  <div v-if="context" class="cd-ctx-card" :class="`cd-sev-${level}`">
    <img v-if="context.thumb_url" class="cd-ctx-card__thumb" :src="context.thumb_url" alt="检测图" />
    <div v-else class="cd-ctx-card__thumb cd-ctx-card__thumb--empty">🌿</div>

    <div class="cd-ctx-card__body">
      <div class="cd-ctx-card__title">
        {{ cropText }}<span v-if="diseaseText"> · {{ diseaseText }}</span>
      </div>
      <div class="cd-ctx-card__meta">
        <span
          class="cd-ctx-card__tag"
          :style="{ backgroundColor: severityColor, color: '#fff' }"
        >
          {{ context.severity_label || '—' }}
        </span>
        <span class="cd-ctx-card__conf">置信度 {{ confText }}</span>
      </div>
    </div>

    <van-icon class="cd-ctx-card__close" name="cross" @click="$emit('close')" />
  </div>
</template>

<script setup>
import { computed } from 'vue'

import { SEVERITY_COLORS } from '@/stores/chat'

const props = defineProps({
  /** DetectionContextOut 结构 */
  context: {
    type: Object,
    default: null,
  },
})

defineEmits(['close'])

const level = computed(() => {
  const v = props.context && props.context.severity_level
  return typeof v === 'number' && v >= 0 && v <= 3 ? v : 0
})

/** 语义色 4 档：0 无 / 1 轻微 / 2 中等 / 3 严重 */
const severityColor = computed(() => SEVERITY_COLORS[level.value])

const cropText = computed(() => {
  const c = props.context || {}
  return c.crop_cn || c.crop || '未知作物'
})

const diseaseText = computed(() => {
  const c = props.context || {}
  return c.disease_cn || c.class_name || ''
})

const confText = computed(() => {
  const c = props.context || {}
  return c.top_conf != null ? `${Math.round(c.top_conf * 100)}%` : '—'
})
</script>

<style scoped>
.cd-ctx-card {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 8px 12px;
  padding: 10px 12px;
  background: var(--color-surface);
  border-radius: var(--radius-card);
  border-left: 4px solid var(--sev-color, var(--severity-0));
  box-shadow: var(--shadow-card);
}

.cd-ctx-card__thumb {
  flex: 0 0 auto;
  width: 54px;
  height: 54px;
  border-radius: 10px;
  object-fit: cover;
  background: var(--color-bg);
}

.cd-ctx-card__thumb--empty {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26px;
}

.cd-ctx-card__body {
  flex: 1;
  min-width: 0;
}

.cd-ctx-card__title {
  font: var(--font-h1);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-ctx-card__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.cd-ctx-card__tag {
  padding: 2px 10px;
  border-radius: var(--radius-button);
  font: var(--font-mini);
  font-weight: 600;
}

.cd-ctx-card__conf {
  font: var(--font-caption);
  color: var(--color-text-muted);
}

.cd-ctx-card__close {
  flex: 0 0 auto;
  font-size: 16px;
  color: var(--color-text-muted);
  padding: 4px;
}
</style>
