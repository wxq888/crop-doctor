<script setup>
/**
 * 检测量趋势柱状图（大屏 & 检测记录管理）。
 * 数据来源：GET /admin/stats/trend → detections[]（§7.5）
 */
import { computed } from 'vue'

import BaseChart from './BaseChart.vue'
import { CHART_COLORS, getChartTheme } from '@/utils/echarts'
import { useThemeStore } from '@/stores/theme'

const props = defineProps({
  /** X 轴日期 ["2026-09-11", ...] */
  days: { type: Array, default: () => [] },
  /** 每日检测量 */
  values: { type: Array, default: () => [] },
  /** 高度 */
  height: { type: String, default: '260px' },
  /** 加载态 */
  loading: { type: Boolean, default: false },
})

const themeStore = useThemeStore()

const option = computed(() => {
  const t = getChartTheme(themeStore.theme)
  // X 轴只显示月-日，避免拥挤
  const labels = props.days.map((d) => (typeof d === 'string' ? d.slice(5) : d))
  return {
    grid: { left: 8, right: 16, top: 24, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: { lineStyle: { color: t.axisLine } },
      axisLabel: { color: t.muted, fontSize: 11 },
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
        data: props.values,
        barMaxWidth: 26,
        itemStyle: {
          borderRadius: [4, 4, 0, 0],
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: CHART_COLORS.primary },
              { offset: 1, color: CHART_COLORS.primaryDark },
            ],
          },
        },
      },
    ],
  }
})
</script>

<template>
  <BaseChart :option="option" :height="height" :loading="loading" />
</template>
