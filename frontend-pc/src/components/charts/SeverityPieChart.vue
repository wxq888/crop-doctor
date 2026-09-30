<script setup>
/**
 * 严重度分布环图（大屏 / 预警中心风险等级分布复用）。
 * 数据来源：GET /admin/stats/trend → severity_dist[]（§7.5）
 *         或 GET /warning/overview → stats{high,mid,low}
 */
import { computed } from 'vue'

import BaseChart from './BaseChart.vue'
import { getChartTheme } from '@/utils/echarts'
import { useThemeStore } from '@/stores/theme'

const props = defineProps({
  /** [{level,label,count}] 或 [{name,value}] */
  dist: { type: Array, default: () => [] },
  height: { type: String, default: '260px' },
  loading: { type: Boolean, default: false },
})

const themeStore = useThemeStore()

/** 语义色（按 level / 名称映射） */
const SEVERITY_COLORS = { 0: '#6B7B71', 1: '#2BA471', 2: '#F5A623', 3: '#E5534B' }
const RISK_COLORS = { high: '#E5534B', mid: '#F5A623', low: '#2BA471' }

function colorOf(item, index) {
  if (item.level !== undefined && SEVERITY_COLORS[item.level]) return SEVERITY_COLORS[item.level]
  if (item.risk && RISK_COLORS[item.risk]) return RISK_COLORS[item.risk]
  const fallback = ['#2BA471', '#F5A623', '#E5534B', '#6B7B71']
  return fallback[index % fallback.length]
}

const option = computed(() => {
  const t = getChartTheme(themeStore.theme)
  const data = props.dist.map((item, i) => ({
    name: item.label || item.name || String(item.level ?? i),
    value: item.count ?? item.value ?? 0,
    itemStyle: { color: colorOf(item, i) },
  }))
  return {
    tooltip: {
      trigger: 'item',
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.tooltipText, fontSize: 12 },
      formatter: '{b}: {c} ({d}%)',
    },
    legend: {
      orient: 'vertical',
      right: 4,
      top: 'center',
      itemWidth: 10,
      itemHeight: 10,
      textStyle: { color: t.text, fontSize: 11 },
    },
    series: [
      {
        name: '分布',
        type: 'pie',
        radius: ['48%', '72%'],
        center: ['38%', '50%'],
        avoidLabelOverlap: true,
        label: { show: false },
        labelLine: { show: false },
        data,
      },
    ],
  }
})
</script>

<template>
  <BaseChart :option="option" :height="height" :loading="loading" />
</template>
