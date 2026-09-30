<script setup>
/**
 * 严重度分级标签（0-3 语义色 + 文字，见 ui-design.md §2.1 / §6）。
 * 分级不只依赖颜色：始终带文字。
 */
import { computed } from 'vue'

const props = defineProps({
  /** 分级：0 无 / 1 轻微 / 2 中等 / 3 严重 */
  level: { type: Number, default: 0 },
  /** 自定义文字（缺省用标准分级文案） */
  label: { type: String, default: '' },
})

/** 分级 → 文案 */
const SEVERITY_LABELS = ['无病害', '轻微', '中等', '严重']

/** 分级 → 颜色（对齐 §2.1 语义色） */
const SEVERITY_COLORS = ['#6B7B71', '#2BA471', '#F5A623', '#E5534B']

const safeLevel = computed(() => {
  const n = Number(props.level)
  return Number.isInteger(n) && n >= 0 && n <= 3 ? n : 0
})
const text = computed(() => props.label || SEVERITY_LABELS[safeLevel.value])
const color = computed(() => SEVERITY_COLORS[safeLevel.value])
</script>

<template>
  <el-tag
    class="severity-tag"
    size="small"
    effect="plain"
    :style="{ color, borderColor: color, backgroundColor: color + '1A' }"
  >
    {{ text }}
  </el-tag>
</template>

<style scoped>
.severity-tag {
  font-weight: 600;
  border-width: 1px;
}
</style>
