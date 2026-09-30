<script setup>
/**
 * 风险等级标签（high / mid / low，带 ⚠ 图标，见 ui-design.md §2.1 / §6）。
 */
import { computed } from 'vue'

const props = defineProps({
  /** 风险等级：high | mid | low */
  risk: { type: String, default: 'low' },
  /** 自定义文字（缺省用标准风险文案） */
  label: { type: String, default: '' },
})

/** 风险 → 文案 / 颜色 */
const RISK_MAP = {
  high: { text: '高风险', color: '#E5534B' },
  mid: { text: '中风险', color: '#F5A623' },
  low: { text: '低风险', color: '#2BA471' },
}

const safeRisk = computed(() => (RISK_MAP[props.risk] ? props.risk : 'low'))
const text = computed(() => props.label || `${RISK_MAP[safeRisk.value].text}`)
const color = computed(() => RISK_MAP[safeRisk.value].color)
</script>

<template>
  <el-tag
    class="risk-tag"
    size="small"
    effect="plain"
    :style="{ color, borderColor: color, backgroundColor: color + '1A' }"
  >
    <span class="risk-tag__icon">⚠</span>{{ text }}
  </el-tag>
</template>

<style scoped>
.risk-tag {
  font-weight: 600;
  border-width: 1px;
}
.risk-tag__icon {
  margin-right: 3px;
}
</style>
