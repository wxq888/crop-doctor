<script setup>
/**
 * ECharts 通用封装（见 impl-pc-admin-v1 §7.2）。
 * - props: option / height / loading
 * - 主题变化或 option 变化时以 notMerge 重绘（§7.4）
 * - 容器尺寸变化自动 resize
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import echarts from '@/utils/echarts'
import { useThemeStore } from '@/stores/theme'

const props = defineProps({
  /** 完整 ECharts option */
  option: { type: Object, default: () => ({}) },
  /** 图表高度 */
  height: { type: String, default: '300px' },
  /** 加载态（渲染 loading 遮罩） */
  loading: { type: Boolean, default: false },
})

const emit = defineEmits(['click'])

const themeStore = useThemeStore()
const chartEl = ref(null)
/** @type {import('echarts').ECharts|null} */
let chart = null
let observer = null

/** 渲染（notMerge 全量重绘，避免残留） */
function render() {
  if (!chart) return
  chart.setOption(props.option || {}, { notMerge: true })
}

/** 加载态切换 */
function syncLoading() {
  if (!chart) return
  if (props.loading) {
    chart.showLoading('default', { text: '加载中', color: '#2BA471', textColor: '#7C8A96' })
  } else {
    chart.hideLoading()
  }
}

onMounted(() => {
  if (!chartEl.value) return
  chart = echarts.init(chartEl.value)
  // 透传导出的图表点击事件（如需数据项点击交互）
  chart.on('click', (params) => emit('click', params))
  render()
  syncLoading()
  // 容器尺寸监听（如侧边栏折叠 / 窗口缩放）
  observer = new ResizeObserver(() => {
    if (chart) chart.resize()
  })
  observer.observe(chartEl.value)
})

onBeforeUnmount(() => {
  if (observer) {
    observer.disconnect()
    observer = null
  }
  if (chart) {
    chart.dispose()
    chart = null
  }
})

// option 变化 → 重绘
watch(
  () => props.option,
  () => render(),
  { deep: true },
)

// 主题变化 → 重绘（§7.4 ECharts 跟随主题）
watch(
  () => themeStore.theme,
  () => render(),
)

// loading 变化
watch(
  () => props.loading,
  () => syncLoading(),
)

defineExpose({
  /** 手动 resize（供父组件调用） */
  resize: () => chart && chart.resize(),
  /** 获取底层实例 */
  getInstance: () => chart,
})
</script>

<template>
  <div ref="chartEl" class="base-chart" :style="{ height }"></div>
</template>

<style scoped>
.base-chart {
  width: 100%;
}
</style>
