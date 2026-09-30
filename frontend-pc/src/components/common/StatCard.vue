<script setup>
/**
 * 统计卡（大屏顶部 4 卡，见 ui-design.md §4.3 ⑤）。
 * 图标 + 数值 + 单位 + 语义色，tone 决定强调色。
 */
import { computed } from 'vue'

const props = defineProps({
  /** 指标名 */
  label: { type: String, required: true },
  /** 数值 */
  value: { type: [Number, String], default: 0 },
  /** 单位 / 后缀 */
  unit: { type: String, default: '' },
  /** 左上角图标（emoji） */
  icon: { type: String, default: '' },
  /**
   * 语义色：success(绿) / warning(琥珀) / danger(红) / primary / neutral
   */
  tone: { type: String, default: 'primary' },
  /** 辅助说明（小字） */
  hint: { type: String, default: '' },
})

/** tone → CSS 变量 */
const toneVar = computed(() => {
  const map = {
    success: 'var(--pc-sev-1)',
    primary: 'var(--pc-primary)',
    warning: 'var(--pc-sev-2)',
    danger: 'var(--pc-sev-3)',
    neutral: 'var(--pc-sev-0)',
  }
  return map[props.tone] || map.primary
})

/** 展示数值：数字带千分位 */
const displayValue = computed(() => {
  if (typeof props.value === 'number' && Number.isFinite(props.value)) {
    return props.value.toLocaleString('en-US')
  }
  return props.value
})
</script>

<template>
  <div class="stat-card cd-panel" :style="{ '--tone': toneVar }">
    <div class="stat-card__top">
      <span class="stat-card__label">{{ label }}</span>
      <span class="stat-card__icon">{{ icon }}</span>
    </div>
    <div class="stat-card__value">
      <span class="stat-card__num">{{ displayValue }}</span>
      <span v-if="unit" class="stat-card__unit">{{ unit }}</span>
    </div>
    <div v-if="hint" class="stat-card__hint">{{ hint }}</div>
  </div>
</template>

<style scoped>
.stat-card {
  padding: 14px 16px;
  border-left: 3px solid var(--tone);
  min-width: 0;
}
.stat-card__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.stat-card__label {
  font: var(--pc-font-sm);
  color: var(--pc-text-muted);
}
.stat-card__icon {
  font-size: 16px;
  opacity: 0.85;
}
.stat-card__value {
  margin-top: 8px;
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.stat-card__num {
  font-size: 26px;
  font-weight: 700;
  color: var(--tone);
  line-height: 1.1;
}
.stat-card__unit {
  font-size: 13px;
  color: var(--pc-text-muted);
}
.stat-card__hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--pc-text-muted);
}
</style>
