<template>
  <div class="cd-page cd-wx">
    <PageNav title="天气详情">
      <template #right>
        <span class="cd-wx-nav__refresh" role="button" aria-label="刷新天气" @click="loadAll">
          <van-icon name="replay" />
          刷新
        </span>
      </template>
    </PageNav>

    <div class="cd-page__body">
      <!-- 降级 / 失败态：整页占位，绝不白屏 -->
      <div v-if="pageState === 'error'" class="cd-wx-error" @click="loadAll">
        <span class="cd-wx-error__icon">🔄</span>
        <div class="cd-wx-error__text">天气服务暂不可用，点击重试</div>
      </div>

      <div v-else-if="pageState === 'loading'" class="cd-wx-error">
        <span class="cd-wx-error__icon">🌍</span>
        <div class="cd-wx-error__text">天气加载中…</div>
      </div>

      <template v-else>
        <!-- ① 实况大卡（延续首页 --gradient-sky 风格） -->
        <div class="cd-wx-hero">
          <div class="cd-wx-hero__top">
            <span>📍 {{ locText }}</span>
            <span>{{ todayText }}</span>
          </div>
          <div class="cd-wx-hero__main">
            <span class="cd-wx-hero__icon">{{ weatherEmoji(nowData && nowData.text) }}</span>
            <span class="cd-wx-hero__temp">{{ Math.round((nowData && nowData.temp) || 0) }}°</span>
            <div class="cd-wx-hero__col">
              <div class="cd-wx-hero__text">{{ (nowData && nowData.text) || '—' }}</div>
              <div class="cd-wx-hero__obs">观测于 {{ obsTimeText }}</div>
            </div>
          </div>
        </div>

        <!-- ② 实况详情网格（2 列 × 4 行，共 8 项） -->
        <div class="cd-card cd-wx-grid">
          <div v-for="item in detailItems" :key="item.label" class="cd-wx-grid__item">
            <div class="cd-wx-grid__label">{{ item.label }}</div>
            <div class="cd-wx-grid__value">{{ item.value }}</div>
          </div>
        </div>

        <!-- ③ 24 小时逐时预报（横向滚动） -->
        <div v-if="hourlyList.length" class="cd-card">
          <div class="cd-wx-sec__title">24 小时预报</div>
          <div class="cd-wx-hours">
            <div v-for="(h, i) in hourlyList" :key="h.fx_time || i" class="cd-wx-hours__item">
              <span class="cd-wx-hours__time">{{ hourLabel(h.fx_time) }}</span>
              <span class="cd-wx-hours__icon">{{ weatherEmoji(h.text) }}</span>
              <span class="cd-wx-hours__temp">{{ Math.round(h.temp) }}°</span>
              <span class="cd-wx-hours__pop">{{ popText(h.pop) }}</span>
            </div>
          </div>
        </div>

        <!-- ④ 7 日预报列表 -->
        <div v-if="forecastList.length" class="cd-card">
          <div class="cd-wx-sec__title">7 日预报</div>
          <div
            v-for="(day, i) in forecastList"
            :key="day.date || i"
            class="cd-wx-day"
          >
            <span class="cd-wx-day__date">{{ dayLabel(day.date, i) }}</span>
            <span class="cd-wx-day__icon">{{ weatherEmoji(day.text_day) }}</span>
            <span class="cd-wx-day__text">{{ day.text_day }}</span>
            <span class="cd-wx-day__range">{{ Math.round(day.temp_min) }}°~{{ Math.round(day.temp_max) }}°</span>
            <span class="cd-wx-day__hum">湿度 {{ day.humidity != null ? Math.round(day.humidity) + '%' : '—' }}</span>
          </div>
        </div>

        <!-- ⑤ 施药建议卡（降雨窗口提示） -->
        <div v-if="sprayAdvice" class="cd-card cd-wx-spray">
          <div class="cd-wx-sec__title">施药建议</div>
          <p class="cd-wx-spray__text">{{ sprayAdvice.advice }}</p>
          <div v-if="sprayAdvice.next_rain_date" class="cd-wx-spray__meta">
            下一降雨日：{{ sprayAdvice.next_rain_date }}
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import PageNav from '@/components/common/PageNav.vue'
import * as weatherApi from '@/api/weather'
import { getLonLat } from '@/utils/geo'
import { weatherEmoji } from '@/utils/weatherIcon'

/**
 * 天气详情页（首页天气卡点击进入）：
 * 实况大卡 → 实况详情网格（8 项）→ 24 小时逐时（横向滚动）→
 * 7 日预报 → 施药建议。任一核心数据失败 → 整页占位可重试，绝不白屏。
 * 定位成功带经纬度查询，失败不传 location（后端默认遵义）。
 */
const pageState = ref('loading') // 'loading' | 'ready' | 'error'
const nowData = ref(null)
const forecastList = ref([])
const hourlyList = ref([])
const sprayAdvice = ref(null)
const geoUsed = ref(false)

/** 后端默认位置（不传 location 时后端用遵义） */
const DEFAULT_LOC_NAME = '遵义'

const WEEK_NAMES = ['日', '一', '二', '三', '四', '五', '六']

const locText = computed(() => (geoUsed.value ? '当前位置' : DEFAULT_LOC_NAME))

const todayText = computed(() => {
  const d = new Date()
  return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEK_NAMES[d.getDay()]}`
})

/** 和风 obsTime（ISO）→ 「MM-dd HH:mm」；缺失/解析失败 → '—' */
const obsTimeText = computed(() => {
  const raw = nowData.value && (nowData.value.obs_time || nowData.value.updated_at)
  if (!raw) return '—'
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return '—'
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
})

/** 可选数值 → 「值 + 单位」；null/undefined → '—' */
function fmtNum(value, unit) {
  if (value == null || value === '') return '—'
  return `${Math.round(value)}${unit}`
}

/** 实况详情网格 8 项（含风向外其他缺失字段都以 '—' 展示，不留空白） */
const detailItems = computed(() => {
  const n = nowData.value || {}
  const dir = n.wind_dir || ''
  const dirText = dir ? (dir.endsWith('风') ? dir : `${dir}风`) : ''
  const scale = n.wind_scale != null && n.wind_scale !== '' ? `${n.wind_scale}级` : ''
  return [
    { label: '体感温度', value: fmtNum(n.feels_like, '°C') },
    { label: '湿度', value: fmtNum(n.humidity, '%') },
    { label: '风向风力', value: [dirText, scale].filter(Boolean).join(' ') || '—' },
    { label: '降水量', value: fmtNum(n.precip, 'mm') },
    { label: '气压', value: fmtNum(n.pressure, 'hPa') },
    { label: '能见度', value: fmtNum(n.vis, 'km') },
    { label: '云量', value: fmtNum(n.cloud, '%') },
    { label: '露点温度', value: fmtNum(n.dew, '°C') },
  ]
})

/** fxTime（ISO）→ 「HH时」（下一小时数据无需精确到分） */
function hourLabel(fxTime) {
  if (!fxTime) return '—'
  const d = new Date(fxTime)
  if (Number.isNaN(d.getTime())) return '—'
  return `${String(d.getHours()).padStart(2, '0')}时`
}

/** 降水概率文案：null → '—'，0 → 「0%」仍显示（有信息量） */
function popText(pop) {
  return pop == null ? '—' : `降水${Math.round(pop)}%`
}

/** 预报日文案：第 1 条 → 今天，否则 → 周X（MM-dd） */
function dayLabel(dateStr, index) {
  if (index === 0) return '今天'
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return dateStr || '—'
  return `周${WEEK_NAMES[d.getDay()]}`
}

onMounted(() => {
  loadAll()
})

/**
 * 加载全部天气数据（实况 + 7 日 + 24h + 施药建议）。
 * 定位失败 → 不传 location；核心实况缺失/降级 → 整页 error 占位。
 */
async function loadAll() {
  pageState.value = 'loading'
  nowData.value = null
  forecastList.value = []
  hourlyList.value = []
  sprayAdvice.value = null
  try {
    const location = await getLonLat()
    geoUsed.value = !!location
    const loc = location || ''
    const [now, forecast, hourly, advice] = await Promise.all([
      weatherApi.getNow(loc),
      weatherApi.getForecast(loc, 7),
      weatherApi.getHourly(loc),
      weatherApi.getSprayAdvice(loc),
    ])
    nowData.value = now && !now.degraded ? now : null
    forecastList.value = forecast && !forecast.degraded ? forecast.list || [] : []
    hourlyList.value = hourly && !hourly.degraded ? hourly.list || [] : []
    sprayAdvice.value = advice && !advice.degraded ? advice : null
    // 核心实况拿不到 → 整页占位（预报/建议随之隐藏）；否则正常渲染
    pageState.value = nowData.value ? 'ready' : 'error'
  } catch (e) {
    nowData.value = null
    forecastList.value = []
    hourlyList.value = []
    sprayAdvice.value = null
    pageState.value = 'error'
  }
}
</script>

<style scoped>
.cd-wx {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: var(--color-bg);
}

.cd-wx-nav__refresh {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font: var(--font-caption);
  color: var(--color-primary);
  font-weight: 600;
  padding: 6px 2px;
  cursor: pointer;
}

/* ---------- 降级 / 加载占位 ---------- */
.cd-wx-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  margin: var(--space-20) var(--space-12);
  padding: 40px 16px;
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  cursor: pointer;
}

.cd-wx-error__icon {
  font-size: 34px;
  line-height: 1;
}

.cd-wx-error__text {
  font: var(--font-body);
  color: var(--color-text-muted);
}

/* ---------- ① 实况大卡 ---------- */
.cd-wx-hero {
  margin: var(--space-12) var(--space-12) var(--space-16);
  padding: 16px 16px 18px;
  border-radius: var(--radius-card);
  background: var(--gradient-sky);
  color: #ffffff;
  box-shadow: var(--shadow-sky);
}

.cd-wx-hero__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font: var(--font-caption);
  color: rgba(255, 255, 255, 0.92);
}

.cd-wx-hero__main {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
}

.cd-wx-hero__icon {
  font-size: 52px;
  line-height: 1;
}

.cd-wx-hero__temp {
  font: 600 56px/1 -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  letter-spacing: -1px;
}

.cd-wx-hero__col {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cd-wx-hero__text {
  font: var(--font-h1);
  color: #ffffff;
}

.cd-wx-hero__obs {
  font: var(--font-mini);
  color: rgba(255, 255, 255, 0.85);
}

/* ---------- 通用卡片 / 区块标题 ---------- */
.cd-wx .cd-card {
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: var(--space-12);
  margin: 0 var(--space-12) var(--space-16);
}

.cd-wx-sec__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font: var(--font-h2);
  color: var(--color-text);
  margin-bottom: 10px;
}

/* 品牌绿标题条（与首页检测卡一致的视觉锚点） */
.cd-wx-sec__title::before {
  content: '';
  width: 4px;
  height: 16px;
  border-radius: 2px;
  background: var(--gradient-brand-135);
}

/* ---------- ② 实况详情网格（2 列） ---------- */
.cd-wx-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.cd-wx-grid__item {
  padding: 12px;
  border-radius: var(--radius-card);
  background: var(--color-bg);
}

.cd-wx-grid__label {
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-wx-grid__value {
  margin-top: 4px;
  font: var(--font-h2);
  color: var(--color-text);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---------- ③ 24 小时逐时（横向滚动） ---------- */
.cd-wx-hours {
  display: flex;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  padding-bottom: 4px;
}

.cd-wx-hours__item {
  flex: 0 0 auto;
  min-width: 58px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  padding: 6px 4px;
  border-radius: var(--radius-card);
  background: var(--color-bg);
}

.cd-wx-hours__item + .cd-wx-hours__item {
  margin-left: 8px;
}

.cd-wx-hours__time {
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-wx-hours__icon {
  font-size: 22px;
  line-height: 1.2;
}

.cd-wx-hours__temp {
  font: var(--font-body);
  font-weight: 600;
  color: var(--color-text);
}

.cd-wx-hours__pop {
  font: var(--font-mini);
  color: var(--color-primary);
}

/* ---------- ④ 7 日预报列表 ---------- */
.cd-wx-day {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
}

.cd-wx-day + .cd-wx-day {
  border-top: 1px solid var(--color-border);
}

.cd-wx-day__date {
  flex: 0 0 52px;
  font: var(--font-body);
  font-weight: 600;
  color: var(--color-text);
}

.cd-wx-day__icon {
  flex: 0 0 auto;
  font-size: 22px;
  line-height: 1.2;
}

.cd-wx-day__text {
  flex: 1;
  min-width: 0;
  font: var(--font-body);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-wx-day__range {
  flex: 0 0 auto;
  font: var(--font-caption);
  color: var(--color-text);
}

.cd-wx-day__hum {
  flex: 0 0 auto;
  width: 64px;
  text-align: right;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

/* ---------- ⑤ 施药建议卡 ---------- */
.cd-wx-spray__text {
  margin: 0;
  font: var(--font-body);
  color: var(--color-text);
  line-height: 1.7;
}

.cd-wx-spray__meta {
  margin-top: 8px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}
</style>
