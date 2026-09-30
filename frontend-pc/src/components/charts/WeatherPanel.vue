<script setup>
/**
 * 天气面板（大屏 & 预警中心）。
 * 数据来源：GET /weather/now + GET /weather/forecast（大屏）
 *         或 GET /warning/overview → now/forecast（预警中心）
 * 天气不可用时显示「暂无天气数据」（降级不报错，§4.2 / §9 限制 1）。
 */
import { computed } from 'vue'

const props = defineProps({
  /** 当前天气对象或 null */
  now: { type: Object, default: null },
  /** 预报数组 [{date,temp_min,temp_max,condition,...}]；容错接受 {list:[...]} 信封 */
  forecast: { type: [Array, Object], default: () => [] },
  /** 是否降级（天气服务不可用） */
  degraded: { type: Boolean, default: false },
  /** 加载态 */
  loading: { type: Boolean, default: false },
  /** 面板标题 */
  title: { type: String, default: '天气 · 施药窗口' },
})

/** 归一化预报数组：上游可能是对象信封（如 {list:[...]}) 或非数组，统一转数组，绝不对其直接调数组方法 */
const forecastList = computed(() => {
  const f = props.forecast
  if (Array.isArray(f)) return f
  if (f && typeof f === 'object' && Array.isArray(f.list)) return f.list
  if (f && typeof f === 'object' && Array.isArray(f.items)) return f.items
  return []
})

/** 是否有可展示的天气数据 */
const hasData = computed(() => !!props.now || forecastList.value.length > 0)

/** 从对象中容错取第一个存在的字段 */
function pick(obj, keys) {
  if (!obj) return undefined
  for (const k of keys) {
    if (obj[k] !== undefined && obj[k] !== null && obj[k] !== '') return obj[k]
  }
  return undefined
}

/** 当前天气展示字段 */
const nowView = computed(() => {
  const n = props.now
  if (!n) return null
  return {
    location: pick(n, ['location', 'city', 'name']) || '当前地区',
    temp: pick(n, ['temp', 'temperature', 'temp_c']),
    humidity: pick(n, ['humidity', 'humidity_pct']),
    condition: pick(n, ['condition', 'text', 'weather']),
    wind: pick(n, ['wind', 'wind_scale', 'wind_dir']),
  }
})

/** 预报卡片展示字段 */
const forecastView = computed(() =>
  forecastList.value.slice(0, 3).map((d) => ({
    date: pick(d, ['date', 'forecast_date', 'fxDate']) || '',
    label: (pick(d, ['date', 'forecast_date', 'fxDate']) || '').slice(5) || '',
    condition: pick(d, ['condition', 'text', 'weather']) || '',
    tempMin: pick(d, ['temp_min', 'tempMin', 'min']),
    tempMax: pick(d, ['temp_max', 'tempMax', 'max']),
    humidity: pick(d, ['humidity']),
  })),
)
</script>

<template>
  <div class="weather-panel">
    <div class="weather-panel__head">
      <span class="weather-panel__title">{{ title }}</span>
      <span class="weather-panel__badge" :class="{ 'is-off': degraded || !hasData }">
        {{ degraded ? '服务未配置' : hasData ? '已同步' : '无数据' }}
      </span>
    </div>

    <div v-if="loading" class="weather-panel__empty">加载中…</div>

    <div v-else-if="!hasData" class="weather-panel__empty">
      <span class="weather-panel__empty-icon">🌤️</span>
      <span>暂无天气数据</span>
      <span class="weather-panel__empty-hint">天气服务未配置或暂不可用，风险引擎降级运行</span>
    </div>

    <template v-else>
      <div v-if="nowView" class="weather-panel__now">
        <div class="weather-panel__now-main">
          <span class="weather-panel__now-temp">{{ nowView.temp !== undefined ? nowView.temp : '--' }}°</span>
          <div class="weather-panel__now-meta">
            <div class="weather-panel__now-loc">{{ nowView.location }}</div>
            <div class="weather-panel__now-cond">{{ nowView.condition || '—' }}</div>
          </div>
        </div>
        <div class="weather-panel__now-extra">
          <span>湿度 {{ nowView.humidity !== undefined ? nowView.humidity + '%' : '--' }}</span>
          <span v-if="nowView.wind">风 {{ nowView.wind }}</span>
        </div>
      </div>

      <div v-if="forecastView.length" class="weather-panel__forecast">
        <div v-for="(d, i) in forecastView" :key="i" class="weather-panel__day">
          <div class="weather-panel__day-date">{{ d.label || d.date }}</div>
          <div class="weather-panel__day-cond">{{ d.condition || '—' }}</div>
          <div class="weather-panel__day-temp">
            <span class="is-min">{{ d.tempMin !== undefined ? d.tempMin : '--' }}°</span>
            <span class="is-sep">/</span>
            <span class="is-max">{{ d.tempMax !== undefined ? d.tempMax : '--' }}°</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.weather-panel {
  padding: 4px 2px;
}
.weather-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.weather-panel__title {
  font-weight: 600;
  color: var(--pc-text);
  font-size: 13px;
}
.weather-panel__badge {
  font-size: 11px;
  color: var(--pc-primary);
  background: var(--pc-primary-soft);
  padding: 2px 8px;
  border-radius: 10px;
}
.weather-panel__badge.is-off {
  color: var(--pc-text-muted);
  background: var(--pc-border);
}
.weather-panel__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 24px 8px;
  color: var(--pc-text-muted);
  font-size: 12px;
  text-align: center;
}
.weather-panel__empty-icon {
  font-size: 26px;
  opacity: 0.7;
}
.weather-panel__empty-hint {
  font-size: 11px;
  opacity: 0.75;
}
.weather-panel__now {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-radius: var(--pc-radius);
  background: var(--pc-primary-soft);
  margin-bottom: 12px;
}
.weather-panel__now-main {
  display: flex;
  align-items: center;
  gap: 12px;
}
.weather-panel__now-temp {
  font-size: 30px;
  font-weight: 700;
  color: var(--pc-primary);
  line-height: 1;
}
.weather-panel__now-loc {
  font-size: 13px;
  font-weight: 600;
  color: var(--pc-text);
}
.weather-panel__now-cond {
  font-size: 12px;
  color: var(--pc-text-muted);
}
.weather-panel__now-extra {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11px;
  color: var(--pc-text-muted);
  text-align: right;
}
.weather-panel__forecast {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.weather-panel__day {
  padding: 10px 8px;
  border: 1px solid var(--pc-border);
  border-radius: var(--pc-radius);
  text-align: center;
}
.weather-panel__day-date {
  font-size: 12px;
  color: var(--pc-text);
  font-weight: 600;
}
.weather-panel__day-cond {
  font-size: 11px;
  color: var(--pc-text-muted);
  margin: 4px 0;
  min-height: 15px;
}
.weather-panel__day-temp {
  font-size: 12px;
}
.weather-panel__day-temp .is-min {
  color: var(--pc-text-muted);
}
.weather-panel__day-temp .is-max {
  color: var(--pc-danger, #e5534b);
  font-weight: 600;
}
</style>
