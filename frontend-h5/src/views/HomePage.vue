<template>
  <div class="cd-page cd-home">
    <!-- ① 顶部品牌问候 + 当天日期（不占滚动区） -->
    <header class="cd-home__header">
      <div class="cd-home__brand">
        <span class="cd-home__logo">🌱</span>
        <span>作物医生</span>
      </div>
      <div class="cd-home__hello-row">
        <span class="cd-home__hello">{{ greeting }}，{{ userStore.displayName }}</span>
        <span class="cd-home__date">{{ todayText }}</span>
      </div>
    </header>

    <div class="cd-page__body">
      <!-- ② 实时天气卡（渐变天空底 + 大号温度 + 迷你 3 日预报；失败/降级 → 占位态）；
           点击整卡 → /#/weather 天气详情页 -->
      <div
        class="cd-weather"
        :class="{ 'cd-weather--degraded': weatherState === 'error' }"
        @click="goWeatherDetail"
      >
        <template v-if="weatherState === 'ready' && weatherNow">
          <div class="cd-weather__top">
            <span class="cd-weather__loc">📍 {{ weatherLoc }}</span>
            <span class="cd-weather__date">{{ todayText }}</span>
          </div>
          <div class="cd-weather__main">
            <span class="cd-weather__icon">{{ weatherEmoji(weatherNow.text) }}</span>
            <span class="cd-weather__temp">{{ Math.round(weatherNow.temp) }}°</span>
            <div class="cd-weather__textcol">
              <div class="cd-weather__text">{{ weatherNow.text }}</div>
              <div class="cd-weather__feels">更新于 {{ updatedAtText }}</div>
            </div>
          </div>
          <div class="cd-weather__stats">
            <span>湿度 {{ Math.round(weatherNow.humidity) }}%</span>
            <i class="cd-weather__sep"></i>
            <span>{{ windText }}</span>
            <i class="cd-weather__sep"></i>
            <span>降水 {{ precipText }}</span>
          </div>
          <div v-if="weatherForecast.length" class="cd-weather__forecast">
            <div
              v-for="(day, index) in weatherForecast"
              :key="day.date || index"
              class="cd-weather__fday"
            >
              <span class="cd-weather__flabel">{{ dayLabel(index) }}</span>
              <span class="cd-weather__ficon">{{ weatherEmoji(day.text_day) }}</span>
              <span class="cd-weather__frange">{{ Math.round(day.temp_min) }}°~{{ Math.round(day.temp_max) }}°</span>
            </div>
          </div>
          <div class="cd-weather__more">查看详情 →</div>
        </template>
        <div v-else-if="weatherState === 'loading'" class="cd-weather__placeholder">
          <span class="cd-weather__placeholder-icon">🌍</span>
          天气加载中…
        </div>
        <div v-else class="cd-weather__placeholder" @click.stop="loadWeather">
          <span class="cd-weather__placeholder-icon">🔄</span>
          天气服务暂不可用，点击重试
        </div>
      </div>

      <!-- ③ 预警卡 · 常驻：有未读风险 → 琥珀风险卡；无风险 → 平安卡（两种状态均可点进预警中心） -->
      <div v-if="latestAlert" class="cd-alert-card" @click="router.push('/alerts')">
        <div class="cd-alert-card__head">
          <div class="cd-alert-card__title">
            <van-icon name="warning-o" />
            {{ latestAlert.disease_cn || latestAlert.disease }}预警
          </div>
          <span class="cd-alert-card__tag">{{ riskLabel(latestAlert.risk_level) }}</span>
        </div>
        <p class="cd-alert-card__content">{{ latestAlert.content }}</p>
        <span class="cd-alert-card__more">进入预警中心 →</span>
      </div>
      <div v-else class="cd-safe-card" @click="router.push('/alerts')">
        <span class="cd-safe-card__shield">🛡️</span>
        <div class="cd-safe-card__main">
          <div class="cd-safe-card__title">当前无风险预警</div>
          <div class="cd-safe-card__sub">25 条病害-气象规则持续监测中</div>
        </div>
        <span class="cd-safe-card__more">进入预警中心 →</span>
      </div>

      <!-- ③ 检测主卡：拍照/相册上传大图区 + 立即检测主按钮 -->
      <div class="cd-card cd-detect">
        <div class="cd-detect__title">病害检测</div>

        <div class="cd-detect__drop" @click="pickAlbum">
          <img v-if="previewUrl" class="cd-detect__preview" :src="previewUrl" alt="待检测图片" />
          <template v-else>
            <div class="cd-detect__icon">📷</div>
            <div class="cd-detect__text">点击拍照或从相册选择叶片照片</div>
            <div class="cd-detect__hint">支持 JPG / PNG / WebP，≤ 10MB</div>
          </template>
        </div>

        <div class="cd-detect__pick">
          <span @click.stop="pickCamera">📷 拍照</span>
          <span @click.stop="pickAlbum">🖼 相册</span>
        </div>

        <div class="cd-detect__actions">
          <van-button round block type="primary" class="cd-btn-main" :loading="uploading" @click="startDetect">
            立即检测
          </van-button>
          <van-button round block plain type="primary" class="cd-btn-sub" @click="onRealtime">
            摄像头实时检测
          </van-button>
        </div>

        <input ref="albumInput" type="file" accept="image/*" hidden @change="onFileChange" />
        <input ref="cameraInput" type="file" accept="image/*" capture="environment" hidden @change="onFileChange" />
      </div>

      <!-- ④ 最近检测一条（无记录 → 友好空态，不再整块消失） -->
      <div class="cd-card cd-recent">
        <div class="cd-recent__head">
          <span>最近检测</span>
          <span class="cd-recent__all" @click.stop="router.push('/records')">全部记录 →</span>
        </div>
        <div v-if="recent" class="cd-recent__item" @click="router.push(`/detection/${recent.id}`)">
          <img class="cd-recent__thumb" :src="recentThumb" alt="检测缩略图" />
          <div class="cd-recent__main">
            <div class="cd-recent__name">{{ recent.disease_cn || recent.top_disease || '未知病害' }}</div>
            <div class="cd-recent__time">{{ formatDateTime(recent.created_at) }}</div>
          </div>
          <SeverityTag
            :level="recent.is_healthy ? 0 : recent.severity_level"
            :label="recent.is_healthy ? '健康' : recent.severity_label"
            :color="recent.is_healthy ? HEALTHY_COLOR : ''"
          />
        </div>
        <div v-else class="cd-recent__empty">
          <div class="cd-recent__empty-icon">🌾</div>
          <div class="cd-recent__empty-text">还没有检测记录，拍张照片试试</div>
          <div class="cd-recent__empty-hint">点击上方上传区选择叶片照片即可开始检测</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { closeToast, showLoadingToast, showToast } from 'vant'

import SeverityTag from '@/components/common/SeverityTag.vue'
import * as detectionApi from '@/api/detection'
import * as warningApi from '@/api/warning'
import * as weatherApi from '@/api/weather'
import { resolveStaticUrl } from '@/api/chat'
import { HEALTHY_COLOR } from '@/stores/chat'
import { formatDateTime } from '@/utils/format'
import { getLonLat } from '@/utils/geo'
import { weatherEmoji } from '@/utils/weatherIcon'
import { useUserStore } from '@/stores/user'

/**
 * 首页（ui-design.md §3.2 ① + H5 改版）：
 * 顶部问候 → 实时天气卡（定位 + 和风实况 + 迷你 3 日预报，点击进天气详情页）→
 * 预警卡（常驻：有风险琥珀卡 / 无风险平安卡）→
 * 检测主卡（上传 + 立即检测）→ 最近检测（含空态）。
 * 底部 TabBar 已覆盖全部一级入口，首页不再设快捷功能行。
 */
const router = useRouter()
const userStore = useUserStore()

const albumInput = ref(null)
const cameraInput = ref(null)
/** 选中的待检测文件 */
const file = ref(null)
const previewUrl = ref('')
/** 是否上传推理中 */
const uploading = ref(false)
/** 最近一条检测记录（null → 空态） */
const recent = ref(null)
/** 最新一条未读预警（null → 平安卡） */
const latestAlert = ref(null)

/* ---------- 实时天气卡状态 ---------- */
/** weatherState: 'loading' | 'ready' | 'error'（接口失败 / degraded 均 → error 占位态） */
const weatherState = ref('loading')
const weatherNow = ref(null)
const weatherForecast = ref([])
/** 是否成功拿到浏览器定位（决定顶部展示文案「当前位置」还是默认城市） */
const geoUsed = ref(false)
/** 后端默认位置（不传 location 时后端用遵义 101260201） */
const DEFAULT_LOC_NAME = '遵义'

/** 星期几中文 */
const WEEK_NAMES = ['日', '一', '二', '三', '四', '五', '六']

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

/** 当天日期文案（如「6月5日 周四」） */
const todayText = computed(() => {
  const d = new Date()
  return `${d.getMonth() + 1}月${d.getDate()}日 周${WEEK_NAMES[d.getDay()]}`
})

/** 天气卡顶部位置文案 */
const weatherLoc = computed(() => (geoUsed.value ? '当前位置' : DEFAULT_LOC_NAME))

/** 实况更新时间（HH:mm；updated_at 缺失或解析失败 → '—'） */
const updatedAtText = computed(() => {
  const raw = weatherNow.value && weatherNow.value.updated_at
  if (!raw) return '—'
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return '—'
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
})

/** 风向 + 风力文案（如「东北风 2级」；字段缺失 → '—'） */
const windText = computed(() => {
  const n = weatherNow.value
  if (!n) return '—'
  const dir = n.wind_dir || ''
  const dirText = dir ? (dir.endsWith('风') ? dir : `${dir}风`) : ''
  const scale = n.wind_scale != null && n.wind_scale !== '' ? `${n.wind_scale}级` : ''
  return [dirText, scale].filter(Boolean).join(' ') || '—'
})

/** 降水文案：实况接口无 precip 字段，取今日预报 precip；无数据 → '—' */
const precipText = computed(() => {
  const today = weatherForecast.value && weatherForecast.value[0]
  if (today && today.precip != null) return `${today.precip}mm`
  return '—'
})

const recentThumb = computed(() => resolveStaticUrl(recent.value && recent.value.thumb_url))

onMounted(() => {
  loadRecent()
  loadLatestAlert()
  loadWeather()
})

/* ---------- 数据加载 ---------- */

/** 最近检测一条（page_size=1） */
async function loadRecent() {
  try {
    const page = await detectionApi.listDetectionRecords({ page: 1, page_size: 1 })
    recent.value = (page && page.items && page.items[0]) || null
  } catch (e) {
    recent.value = null
  }
}

/** 最新一条未读预警（unread_only=1 取第 1 条；无 → 平安卡） */
async function loadLatestAlert() {
  try {
    const page = await warningApi.listAlerts({ page: 1, page_size: 1, unread_only: true })
    latestAlert.value = (page && page.items && page.items[0]) || null
  } catch (e) {
    latestAlert.value = null
  }
}

/**
 * 实时天气 + 迷你 3 日预报。
 * 定位失败（getLonLat 返回 null）→ 不传 location，用后端默认位置，页面照常展示。
 * 接口失败 / degraded → weatherState='error' 占位卡（可点重试），绝不抛错白屏。
 */
async function loadWeather() {
  weatherState.value = 'loading'
  weatherNow.value = null
  weatherForecast.value = []
  try {
    const location = await getLonLat()
    geoUsed.value = !!location
    const [now, forecast] = await Promise.all([
      weatherApi.getNow(location || ''),
      weatherApi.getForecast(location || ''),
    ])
    weatherNow.value = now && now.degraded ? null : now
    weatherForecast.value = (forecast && forecast.list) || []
    weatherState.value = weatherNow.value ? 'ready' : 'error'
  } catch (e) {
    weatherNow.value = null
    weatherForecast.value = []
    weatherState.value = 'error'
  }
}

/** 迷你预报条日期文案：第 1/2/3 条 → 今 / 明 / 后 */
function dayLabel(index) {
  return ['今', '明', '后'][index] || '—'
}

/** 天气卡点击 → 天气详情页（降级占位态的重试已 stopPropagation，不会误跳） */
function goWeatherDetail() {
  router.push('/weather')
}

/** 风险等级 → 文案（§6：不只依赖颜色，始终带文字） */
function riskLabel(level) {
  if (level === 'high') return '高风险'
  if (level === 'mid') return '中风险'
  if (level === 'low') return '低风险'
  return '风险'
}

/* ---------- 检测交互 ---------- */

/** 触发相册选择 */
function pickAlbum() {
  albumInput.value && albumInput.value.click()
}

/** 触发拍照（移动端 capture） */
function pickCamera() {
  cameraInput.value && cameraInput.value.click()
}

/** 文件选中：预览 + 校验大小 */
function onFileChange(e) {
  const f = e.target.files && e.target.files[0]
  e.target.value = '' // 允许重复选择同一文件
  if (!f) return
  if (f.size > 10 * 1024 * 1024) {
    showToast('图片不能超过 10MB，请重新选择')
    return
  }
  file.value = f
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(f)
}

/** 立即检测：上传 → 推理 → 跳检测详情 */
async function startDetect() {
  if (uploading.value) return
  if (!file.value) {
    showToast('请先选择叶片照片')
    return
  }
  uploading.value = true
  showLoadingToast({ message: 'AI 识别中…', forbidClick: true, duration: 0 })
  try {
    const record = await detectionApi.uploadDetectionImage(file.value)
    closeToast()
    showToast('检测完成')
    // 清空选择（返回首页时不再残留旧图）
    file.value = null
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
    loadRecent()
    router.push(`/detection/${record.id}`)
  } catch (e) {
    // 2001/2002/2003 等错误已由拦截器统一 toast（如「未检出叶片」）
  } finally {
    closeToast()
    uploading.value = false
  }
}

/** 摄像头实时检测：进入实时检测页（抓帧 → WS → 叠加画框） */
function onRealtime() {
  router.push('/realtime')
}
</script>

<style scoped>
.cd-home {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height 让内容撑开页面（tokens.css body overflow-y:auto）；
     padding-bottom 防止滚到底部时最后元素被固定 TabBar 遮挡 */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

/* ---------- ① 顶部问候 ---------- */
.cd-home__header {
  flex: 0 0 auto;
  padding: 14px 16px 4px;
  padding-top: calc(14px + env(safe-area-inset-top));
}

.cd-home__brand {
  display: flex;
  align-items: center;
  gap: 6px;
  font: var(--font-h2);
  color: var(--color-primary);
  font-weight: 600;
}

.cd-home__logo {
  font-size: 20px;
}

.cd-home__hello-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-top: 6px;
}

.cd-home__hello {
  font: var(--font-body);
  color: var(--color-text-muted);
}

.cd-home__date {
  font: var(--font-mini);
  color: var(--color-text-muted);
}

/* ---------- ② 实时天气卡（渐变天空底，整卡可点进详情页） ---------- */
.cd-weather {
  margin: 8px var(--space-12) var(--space-16);
  padding: 14px 14px 12px;
  border-radius: var(--radius-card);
  background: var(--gradient-sky);
  color: #ffffff;
  box-shadow: var(--shadow-sky);
  cursor: pointer;
}

.cd-weather--degraded {
  /* 降级态：灰底 + 中性投影，保持占位高度不塌陷 */
  background: var(--gradient-muted);
  box-shadow: var(--shadow-card);
}

.cd-weather__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font: var(--font-caption);
  color: rgba(255, 255, 255, 0.92);
}

.cd-weather__main {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 10px 0 8px;
}

.cd-weather__icon {
  font-size: 44px;
  line-height: 1;
}

.cd-weather__temp {
  font: 600 46px/1 -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  letter-spacing: -1px;
}

.cd-weather__textcol {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.cd-weather__text {
  font: var(--font-h2);
  color: #ffffff;
}

.cd-weather__feels {
  font: var(--font-mini);
  color: rgba(255, 255, 255, 0.85);
}

.cd-weather__stats {
  display: flex;
  align-items: center;
  gap: 8px;
  font: var(--font-caption);
  color: rgba(255, 255, 255, 0.92);
}

.cd-weather__sep {
  width: 1px;
  height: 10px;
  background: rgba(255, 255, 255, 0.45);
}

/* 迷你 3 日预报条 */
.cd-weather__forecast {
  display: flex;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.25);
}

.cd-weather__fday {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  font: var(--font-caption);
  color: #ffffff;
}

.cd-weather__flabel {
  color: rgba(255, 255, 255, 0.85);
}

.cd-weather__ficon {
  font-size: 20px;
  line-height: 1.2;
}

.cd-weather__frange {
  color: rgba(255, 255, 255, 0.95);
}

/* 「查看详情 →」提示（右下角小字，适老化：≥12px 且与背景对比充足） */
.cd-weather__more {
  margin-top: 10px;
  text-align: right;
  font: var(--font-mini);
  font-weight: 600;
  color: rgba(255, 255, 255, 0.95);
}

/* 降级 / 加载占位 */
.cd-weather__placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 96px;
  font: var(--font-body);
  color: rgba(255, 255, 255, 0.95);
}

.cd-weather__placeholder-icon {
  font-size: 24px;
}

/* ---------- ③ 预警卡 · 常驻 ---------- */
/* 风险卡：琥珀渐变 + 左色条 + 等级标签 */
.cd-alert-card {
  position: relative;
  margin: 0 var(--space-12) var(--space-16);
  padding: 12px 12px 12px 16px;
  border-radius: var(--radius-card);
  background: var(--alert-amber-bg);
  border-left: 4px solid var(--severity-2);
  box-shadow: var(--shadow-card);
}

.cd-alert-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.cd-alert-card__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font: var(--font-h2);
  color: var(--alert-amber-title);
}

.cd-alert-card__title :deep(.van-icon) {
  color: var(--severity-2);
}

.cd-alert-card__tag {
  flex: 0 0 auto;
  padding: 2px 10px;
  border-radius: 999px;
  background: rgba(245, 166, 35, 0.18);
  color: var(--alert-amber-text);
  font: 600 var(--font-mini);
}

.cd-alert-card__content {
  margin: 6px 0 0;
  font: var(--font-caption);
  color: var(--alert-amber-sub);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cd-alert-card__more {
  display: inline-block;
  margin-top: 6px;
  font: var(--font-mini);
  color: var(--severity-2);
  font-weight: 600;
}

/* 平安卡：品牌绿浅底 + 盾牌（无预警时常驻展示，可进预警中心） */
.cd-safe-card {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0 var(--space-12) var(--space-16);
  padding: 12px 12px 12px 16px;
  border-radius: var(--radius-card);
  background: var(--color-primary-soft);
  border-left: 4px solid var(--color-primary);
  box-shadow: var(--shadow-card);
}

.cd-safe-card__shield {
  font-size: 30px;
  line-height: 1;
}

.cd-safe-card__main {
  flex: 1;
  min-width: 0;
}

.cd-safe-card__title {
  font: var(--font-h2);
  color: var(--color-primary-dark);
}

.cd-safe-card__sub {
  margin-top: 2px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-safe-card__more {
  flex: 0 0 auto;
  font: var(--font-mini);
  color: var(--color-primary);
  font-weight: 600;
}

/* ---------- 通用卡片 ---------- */
.cd-card {
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: var(--space-12);
  margin: 0 var(--space-12) var(--space-16);
}

/* ---------- ③ 检测主卡 ---------- */
.cd-detect__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font: var(--font-h2);
  color: var(--color-text);
  margin-bottom: 10px;
}

/* 品牌绿标题条（视觉锚点） */
.cd-detect__title::before {
  content: '';
  width: 4px;
  height: 16px;
  border-radius: 2px;
  background: var(--gradient-brand-135);
}

.cd-detect__drop {
  min-height: 190px;
  border: 1.5px dashed var(--color-border);
  border-radius: var(--radius-card);
  background: var(--color-bg);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  overflow: hidden;
  cursor: pointer;
}

.cd-detect__preview {
  width: 100%;
  height: 220px;
  object-fit: contain;
}

.cd-detect__icon {
  font-size: 46px;
}

.cd-detect__text {
  font: var(--font-body);
  color: var(--color-text);
}

.cd-detect__hint {
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-detect__pick {
  display: flex;
  justify-content: center;
  gap: 32px;
  margin: 10px 0 2px;
}

.cd-detect__pick span {
  font: var(--font-caption);
  color: var(--color-primary);
  font-weight: 600;
  padding: 4px 6px;
}

.cd-detect__actions {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 主按钮：品牌绿胶囊大按钮（适老化：大按钮） */
.cd-btn-main {
  height: 48px;
  border-radius: var(--radius-button);
  font-size: 16px;
  font-weight: 600;
  background: var(--gradient-brand-135);
  border: none;
}

.cd-btn-sub {
  height: 44px;
  border-radius: var(--radius-button);
  font-size: 15px;
}

/* ---------- ④ 最近检测 ---------- */
.cd-recent__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font: var(--font-h2);
  color: var(--color-text);
  margin-bottom: 10px;
}

.cd-recent__all {
  font: var(--font-caption);
  color: var(--color-text-muted);
  font-weight: 400;
}

.cd-recent__item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 0;
}

.cd-recent__thumb {
  flex: 0 0 auto;
  width: 56px;
  height: 56px;
  border-radius: 10px;
  object-fit: cover;
  background: var(--color-bg);
}

.cd-recent__main {
  flex: 1;
  min-width: 0;
}

.cd-recent__name {
  font: var(--font-body);
  font-weight: 500;
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-recent__time {
  margin-top: 4px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

/* 空态（无检测记录时常驻展示） */
.cd-recent__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 18px 0 12px;
}

.cd-recent__empty-icon {
  font-size: 34px;
  line-height: 1;
}

.cd-recent__empty-text {
  font: var(--font-body);
  color: var(--color-text);
}

.cd-recent__empty-hint {
  font: var(--font-mini);
  color: var(--color-text-muted);
}
</style>
