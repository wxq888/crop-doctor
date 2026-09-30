<script setup>
/**
 * 健康率走势折线图（大屏）。
 * 数据来源：GET /admin/stats/trend → detections[] 与 healthy[]（§7.5）
 * 健康率 = healthy / detections（无真值支撑，仅反映 healthy 类占比，见 §9 限制 5）。
 */
import { computed } from 'vue'

import BaseChart from './BaseChart.vue'
import { CHART_COLORS, getChartTheme } from '@/utils/echarts'
import { useThemeStore } from '@/stores/theme'

const props = defineProps({
  /** X 轴日期 */
  days: { type: Array, default: () => [] },
  /** 每日健康数 */
  healthy: { type: Array, default: () => [] },
  /** 每日检测总量（用于计算健康率分母） */
  totals: { type: Array, default: () => [] },
  height: { type: String, default: '260px' },
  loading: { type: Boolean, default: false },
})

const themeStore = useThemeStore()

const option = computed(() => {
  const t = getChartTheme(themeStore.theme)
  const labels = props.days.map((d) => (typeof d === 'string' ? d.slice(5) : d))
  const rates = props.days.map((_, i) => {
    const total = Number(props.totals[i]) || 0
    const healthy = Number(props.healthy[i]) || 0
    if (total <= 0) return 0
    return Number(((healthy / total) * 100).toFixed(1))
  })
  return {
    grid: { left: 8, right: 16, top: 24, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => `${v}%`,
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: labels,
      axisLine: { lineStyle: { color: t.axisLine } },
      axisLabel: { color: t.muted, fontSize: 11 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      max: 100,
      axisLabel: { color: t.muted, fontSize: 11, formatter: '{value}%' },
      splitLine: { lineStyle: { color: t.splitLine } },
    },
    series: [
      {
        name: '健康率',
        type: 'line',
        smooth: true,
        symbolSize: 6,
        data: rates,
        lineStyle: { width: 2.5, color: CHART_COLORS.primary },
        itemStyle: { color: CHART_COLORS.primary },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(43,164,113,0.30)' },
              { offset: 1, color: 'rgba(43,164,113,0.02)' },
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
