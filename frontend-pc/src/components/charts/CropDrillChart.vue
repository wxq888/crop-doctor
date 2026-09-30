<script setup>
/**
 * 按作物下钻图（条形，大屏）。
 * 数据来源：GET /admin/stats/trend → by_crop[]（§7.5）
 * 点击某作物 → 触发 drill 事件，父组件跳转检测记录页并带 crop 筛选项。
 */
import { computed } from 'vue'

import BaseChart from './BaseChart.vue'
import { CHART_COLORS, getChartTheme } from '@/utils/echarts'
import { useThemeStore } from '@/stores/theme'

const props = defineProps({
  /** [{crop,crop_cn,count}] */
  crops: { type: Array, default: () => [] },
  height: { type: String, default: '260px' },
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['drill'])

const themeStore = useThemeStore()

const option = computed(() => {
  const t = getChartTheme(themeStore.theme)
  const names = props.crops.map((i) => i.crop_cn || i.crop || '未知')
  const counts = props.crops.map((i) => i.count || 0)
  return {
    grid: { left: 8, right: 16, top: 24, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      data: names,
      axisLine: { lineStyle: { color: t.axisLine } },
      axisLabel: { color: t.text, fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: t.splitLine } },
      axisLabel: { color: t.muted, fontSize: 11 },
    },
    series: [
      {
        name: '检测量',
        type: 'bar',
        data: counts,
        barMaxWidth: 30,
        itemStyle: { borderRadius: [4, 4, 0, 0], color: CHART_COLORS.primary },
      },
    ],
  }
})

/** 图表点击 → 按索引取作物并抛出下钻事件 */
function onChartClick(params) {
  const idx = params && typeof params.dataIndex === 'number' ? params.dataIndex : -1
  const item = props.crops[idx]
  if (!item) return
  emit('drill', item)
}
</script>

<template>
  <BaseChart :option="option" :height="height" :loading="loading" @click="onChartClick" />
</template>
