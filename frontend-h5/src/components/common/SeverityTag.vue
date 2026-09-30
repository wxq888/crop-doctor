<template>
  <span class="cd-sev-tag" :style="{ color: tagColor, backgroundColor: soft, borderColor: tagColor }">
    <i class="cd-sev-tag__dot" :style="{ backgroundColor: tagColor }"></i>
    {{ label || defaultLabel }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

import { SEVERITY_COLORS } from '@/stores/chat'

/**
 * 分级标签（四级语义色，ui-design.md §2.1）：
 * 0 无（中性灰）/ 1 轻微（品牌绿）/ 2 中等（琥珀）/ 3 严重（红）。
 * 不只依赖颜色——始终带文字 + 色点（§6 无障碍）。
 */
const props = defineProps({
  /** 分级 0~3 */
  level: { type: Number, default: 0 },
  /** 展示文字，缺省按级别取 无/轻微/中等/严重 */
  label: { type: String, default: '' },
  /** 覆写语义色（如健康=品牌绿）；为空时按 level 取四级语义色 */
  color: { type: String, default: '' },
})

const DEFAULT_LABELS = ['无', '轻微', '中等', '严重']

const safeLevel = computed(() =>
  typeof props.level === 'number' && props.level >= 0 && props.level <= 3 ? props.level : 0,
)
const tagColor = computed(() => props.color || SEVERITY_COLORS[safeLevel.value])
/** 8 位 hex 追加透明度，做同色浅底 */
const soft = computed(() => `${tagColor.value}1f`)
const defaultLabel = computed(() => DEFAULT_LABELS[safeLevel.value])
</script>

<style scoped>
.cd-sev-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 10px;
  border-radius: var(--radius-button);
  border: 1px solid transparent;
  font: var(--font-mini);
  font-weight: 600;
  white-space: nowrap;
}

.cd-sev-tag__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
</style>
