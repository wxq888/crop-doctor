<script setup>
/**
 * ⑤ 实时监控大屏（ui-design.md §4.3 / impl-pc-admin-v1 §7.5、§7.6）。
 * 顶部统计卡 + 检测量趋势 + 健康率走势 + 患病率排行 + 严重度分布 + 按作物下钻 + 天气面板 + 实时事件流。
 * REST 聚合数据 30s 轮询；事件流与增量计数由 WS 驱动（连接在 AdminLayout 建立）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/common/PageHeader.vue'
import StatCard from '@/components/common/StatCard.vue'
import TrendBarChart from '@/components/charts/TrendBarChart.vue'
import HealthLineChart from '@/components/charts/HealthLineChart.vue'
import DiseaseRankChart from '@/components/charts/DiseaseRankChart.vue'
import SeverityPieChart from '@/components/charts/SeverityPieChart.vue'
import CropDrillChart from '@/components/charts/CropDrillChart.vue'
import WeatherPanel from '@/components/charts/WeatherPanel.vue'
import EventStream from '@/components/monitor/EventStream.vue'

import { getStatsOverview, getStatsTrend } from '@/api/admin'
import { getNow, getForecast } from '@/api/weather'
import { useMonitorStore } from '@/stores/monitor'

const router = useRouter()
const monitorStore = useMonitorStore()

const overview = ref({
  today_detections: 0,
  today_new_users: 0,
  total_users: 0,
  total_detections: 0,
  today_healthy_rate: 0,
  today_avg_conf: 0,
  warnings_active: 0,
  pending_feedbacks: 0,
})

const trend = ref({
  days: [],
  detections: [],
  healthy: [],
  warnings: [],
  disease_rank: [],
  severity_dist: [],
  by_crop: [],
})

const weather = ref({ now: null, forecast: [], degraded: false })
const loading = ref({ overview: false, trend: false, weather: false })

/** 统计卡数值（叠加 WS 增量，§7.6） */
const todayDetections = computed(() => (overview.value.today_detections || 0) + monitorStore.detectionDelta)
const warningsActive = computed(() => (overview.value.warnings_active || 0) + monitorStore.warningDelta)
const pendingFeedbacks = computed(() => (overview.value.pending_feedbacks || 0) + monitorStore.feedbackDelta)

/** 健康率（%）：后端给出 0~1 小数 */
const healthyRateText = computed(() => {
  const v = Number(overview.value.today_healthy_rate) || 0
  return `${(v <= 1 ? v * 100 : v).toFixed(1)}%`
})

/** 平均置信度（%）：top_conf 均值，无真值支撑，仅作代理指标 */
const avgConfText = computed(() => {
  const v = Number(overview.value.today_avg_conf) || 0
  return `${(v <= 1 ? v * 100 : v).toFixed(1)}%`
})

let pollTimer = null

/** 加载统计概览 */
async function loadOverview() {
  loading.value.overview = true
  try {
    const data = await getStatsOverview()
    if (data) overview.value = { ...overview.value, ...data }
  } catch (e) {
    // 后端未就绪时保持默认值
  } finally {
    loading.value.overview = false
  }
}

/** 加载趋势（近 7 日） */
async function loadTrend() {
  loading.value.trend = true
  try {
    const data = await getStatsTrend(7)
    if (data) trend.value = { ...trend.value, ...data }
  } catch (e) {
    // 静默
  } finally {
    loading.value.trend = false
  }
}

/** 加载天气（降级时显示空态） */
async function loadWeather() {
  loading.value.weather = true
  try {
    const [nowRes, fcRes] = await Promise.all([getNow(), getForecast(undefined, 3)])
    // 后端契约：GET /weather/forecast → data = { list: [...], degraded }
    // （list 字段名同时是 H5 端天气契约，不可要求后端改，前端只做展示层归一）
    const fc = fcRes && typeof fcRes === 'object' && !Array.isArray(fcRes) ? fcRes : {}
    const list = Array.isArray(fcRes) ? fcRes : Array.isArray(fc.list) ? fc.list : Array.isArray(fc.items) ? fc.items : []
    const degraded = !!(fc.degraded || (nowRes && nowRes.degraded))
    weather.value = {
      now: degraded || !nowRes || typeof nowRes !== 'object' || Array.isArray(nowRes) ? null : nowRes,
      forecast: list,
      degraded,
    }
  } catch (e) {
    weather.value = { now: null, forecast: [], degraded: true }
  } finally {
    loading.value.weather = false
  }
}

/** 按作物下钻 → 跳检测记录页并带 crop 查询 */
function handleDrill(item) {
  const crop = item.crop || item.crop_cn
  if (!crop) return
  router.push({ name: 'detections', query: { crop } })
}

onMounted(() => {
  loadOverview()
  loadTrend()
  loadWeather()
  // 聚合数据 30s 轮询；事件流由 WS 驱动
  pollTimer = setInterval(() => {
    loadOverview()
    loadTrend()
  }, 30000)
})

onBeforeUnmount(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})
</script>

<template>
  <div class="dashboard">
    <PageHeader
      title="实时监控大屏"
      subtitle="全局检测 / 预警 / 工单实时态势 · 聚合数据 30s 自动刷新，事件流走 WebSocket"
    >
      <template #actions>
        <el-tag :type="monitorStore.connected ? 'success' : 'info'" effect="plain" size="small">
          {{ monitorStore.connected ? '实时通道已连接' : '实时通道未连接' }}
        </el-tag>
      </template>
    </PageHeader>

    <!-- 顶部统计卡 -->
    <div class="dash-stats">
      <StatCard label="今日检测" :value="todayDetections" icon="🔍" tone="primary" hint="含本会话实时增量" />
      <StatCard label="平均置信度" :value="avgConfText" icon="🎯" tone="success" hint="检测结果 top_conf 均值" />
      <StatCard label="今日健康率" :value="healthyRateText" icon="🌿" tone="success" hint="healthy 类占比" />
      <StatCard label="预警中" :value="warningsActive" icon="⚠️" tone="warning" hint="近 24h 生效预警" />
      <StatCard label="待回复工单" :value="pendingFeedbacks" icon="💬" tone="danger" hint="status=pending" />
    </div>

    <div class="dash-grid">
      <!-- 主区 -->
      <div class="dash-main">
        <div class="cd-panel dash-panel">
          <div class="dash-panel__title">检测量趋势（近 7 日）</div>
          <TrendBarChart
            :days="trend.days"
            :values="trend.detections"
            :loading="loading.trend"
            height="248px"
          />
        </div>

        <div class="dash-2col">
          <div class="cd-panel dash-panel">
            <div class="dash-panel__title">健康率走势</div>
            <HealthLineChart
              :days="trend.days"
              :healthy="trend.healthy"
              :totals="trend.detections"
              :loading="loading.trend"
              height="230px"
            />
          </div>
          <div class="cd-panel dash-panel">
            <div class="dash-panel__title">患病率排行 Top10</div>
            <DiseaseRankChart :rank="trend.disease_rank" :loading="loading.trend" height="230px" />
          </div>
        </div>

        <div class="dash-3col">
          <div class="cd-panel dash-panel">
            <div class="dash-panel__title">严重度分布</div>
            <SeverityPieChart :dist="trend.severity_dist" :loading="loading.trend" height="220px" />
          </div>
          <div class="cd-panel dash-panel">
            <div class="dash-panel__title">按作物下钻（点击进入记录）</div>
            <CropDrillChart :crops="trend.by_crop" :loading="loading.trend" height="220px" @drill="handleDrill" />
          </div>
          <div class="cd-panel dash-panel">
            <WeatherPanel
              :now="weather.now"
              :forecast="weather.forecast"
              :degraded="weather.degraded"
              :loading="loading.weather"
            />
          </div>
        </div>
      </div>

      <!-- 右侧事件流 -->
      <div class="cd-panel dash-side">
        <EventStream />
      </div>
    </div>
  </div>
</template>

<style scoped>
.dash-stats {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.dash-grid {
  display: grid;
  grid-template-columns: minmax(0, 2.1fr) minmax(280px, 1fr);
  gap: 16px;
  align-items: start;
}
.dash-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}
.dash-panel {
  padding: 14px 16px;
}
.dash-panel__title {
  font-weight: 600;
  color: var(--pc-text);
  font-size: 13px;
  margin-bottom: 8px;
}
.dash-2col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.dash-3col {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.dash-side {
  padding: 14px 16px;
  height: 640px;
  position: sticky;
  top: 0;
}

/* 1366 宽度下压缩统计卡间距 */
@media (max-width: 1500px) {
  .dash-stats {
    gap: 10px;
  }
  .dash-grid {
    grid-template-columns: minmax(0, 1.9fr) minmax(260px, 1fr);
  }
}
</style>
