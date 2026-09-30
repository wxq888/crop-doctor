<script setup>
/**
 * 患病率排行（横向条形 Top10，大屏）。
 * 数据来源：GET /admin/stats/trend → disease_rank[]（§7.5）
 */
import { computed } from 'vue'

import BaseChart from './BaseChart.vue'
import { CHART_COLORS, getChartTheme } from '@/utils/echarts'
import { useThemeStore } from '@/stores/theme'

const props = defineProps({
  /** [{disease,disease_cn,count}] */
  rank: { type: Array, default: () => [] },
  height: { type: String, default: '260px' },
  loading: { type: Boolean, default: false },
})

const themeStore = useThemeStore()

const option = computed(() => {
  const t = getChartTheme(themeStore.theme)
  // 升序排列，横向条形自下而上，最长为顶部
  const sorted = [...props.rank].sort((a, b) => (a.count || 0) - (b.count || 0))
  const names = sorted.map((i) => i.disease_cn || i.disease || '未知')
  const counts = sorted.map((i) => i.count || 0)
  return {
    grid: { left: 8, right: 28, top: 12, bottom: 4, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 },
    },
    xAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: t.splitLine } },
      axisLabel: { color: t.muted, fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      data: names,
      axisLine: { lineStyle: { color: t.axisLine } },
      axisLabel: { color: t.text, fontSize: 11 },
      axisTick: { show: false },
    },
    series: [
      {
        name: '检出次数',
        type: 'bar',
        data: counts,
        barMaxWidth: 14,
        label: { show: true, position: 'right', color: t.muted, fontSize: 11 },
        itemStyle: {
          borderRadius: [0, 4, 4, 0],
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 1,
            y2: 0,
            colorStops: [
              { offset: 0, color: CHART_COLORS.warning },
              { offset: 1, color: CHART_COLORS.danger },
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
