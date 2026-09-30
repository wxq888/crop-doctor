/**
 * 浏览器地理位置工具（H5 各页共用）。
 *
 * 目标：为「按用户实际位置查询天气」提供统一入口 —— 拿到浏览器定位后拼成
 * 和风天气原生支持的 `经度,纬度` 字符串（⚠️ 经度在前、纬度在后）。
 *
 * 设计原则（最重要）：**永不抛错**。任何一步失败（不支持 / 用户拒绝 / 超时 /
 * 非 HTTPS）都返回 `null`，由调用方决定回退策略（不传 location，后端用自己的
 * 默认位置）。这样天气降级展示不会被定位问题破坏。
 *
 * 会话内缓存：模块级变量 + sessionStorage 双保险 —— 避免每次进页面都弹权限。
 */

import { showToast } from 'vant'

/** sessionStorage 缓存键：成功的经纬度 */
const KEY_LONLAT = 'cd_geo_lonlat'
/** sessionStorage 缓存键：本次会话已拒绝 / 不可用（避免反复请求与反复提示） */
const KEY_UNAVAILABLE = 'cd_geo_unavailable'

/**
 * 模块级缓存（页面内导航共享，不随组件卸载丢失）。
 * - `undefined`：尚未解析
 * - `null`：已解析但失败（不支持/拒绝/超时）
 * - `string`：成功，形如 `"106.710000,26.570000"`
 */
let cachedLonLat = undefined
/** 进行中的定位 Promise，用于并发去重，保证 getCurrentPosition 只被调一次 */
let inFlight = null
/** 权限拒绝提示只弹一次的模块级标记 */
let deniedToastShown = false

/** 安全读 sessionStorage（隐私模式下可能抛错） */
function readSession(key) {
  try {
    return sessionStorage.getItem(key)
  } catch (e) {
    return null
  }
}

/** 安全写 sessionStorage（隐私模式下可能抛错，忽略即可） */
function writeSession(key, value) {
  try {
    sessionStorage.setItem(key, value)
  } catch (e) {
    /* 存储不可用时静默降级为仅内存缓存 */
  }
}

/**
 * 经纬度 → `"经度,纬度"`。
 * 和风天气要求经纬度最多 6 位小数，故统一 `toFixed(6)` 后拼接。
 * @param {number} longitude 经度
 * @param {number} latitude 纬度
 * @returns {string}
 */
function formatLonLat(longitude, latitude) {
  return `${Number(longitude).toFixed(6)},${Number(latitude).toFixed(6)}`
}

/**
 * 判断当前环境是否支持地理定位（含非 HTTPS 场景下 API 缺失的兜底）。
 * @returns {boolean}
 */
function isSupported() {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.geolocation &&
    typeof navigator.geolocation.getCurrentPosition === 'function'
  )
}

/**
 * 权限被拒绝时给用户一次轻提示，且在会话内不重复弹。
 */
function notifyDeniedOnce() {
  if (deniedToastShown) return
  deniedToastShown = true
  try {
    showToast('未获取定位权限，天气将按默认位置显示')
  } catch (e) {
    /* showToast 在极端环境下可能不可用，忽略 */
  }
}

/**
 * 获取浏览器位置并返回 `"经度,纬度"` 字符串。
 *
 * 成功 → 返回字符串；任何失败 → 返回 `null`（不抛错）。
 * 结果在会话内缓存：后续调用直接命中缓存，不再触发定位请求。
 *
 * @param {{timeout?: number}} [options]
 * @param {number} [options.timeout=8000] 定位超时（毫秒）
 * @returns {Promise<string|null>} `"经度,纬度"` 或 `null`
 */
export async function getLonLat({ timeout = 8000 } = {}) {
  // 1) 内存缓存命中（含已解析的失败态 null）
  if (cachedLonLat !== undefined) return cachedLonLat

  // 2) sessionStorage 缓存命中（跨页面刷新）
  const stored = readSession(KEY_LONLAT)
  if (stored) {
    cachedLonLat = stored
    return stored
  }

  // 3) 本次会话已确认不可用（拒绝 / 不支持），直接返回失败态，不再请求
  if (readSession(KEY_UNAVAILABLE) === '1') {
    cachedLonLat = null
    return null
  }

  // 4) 并发去重：同一时刻多次调用共用同一个定位 Promise
  if (inFlight) return inFlight

  inFlight = new Promise((resolve) => {
    if (!isSupported()) {
      // 不支持定位（含非 HTTPS 场景）：静默失败，由调用方回退
      resolve(null)
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const coords = (pos && pos.coords) || {}
        if (coords.longitude == null || coords.latitude == null) {
          resolve(null)
          return
        }
        resolve(formatLonLat(coords.longitude, coords.latitude))
      },
      (err) => {
        // 1 = PERMISSION_DENIED；拒绝时轻提示一次
        if (err && err.code === 1) {
          notifyDeniedOnce()
        }
        resolve(null)
      },
      {
        // 关闭高精度以加快返回（天气无需米级精度）
        enableHighAccuracy: false,
        // 允许 5 分钟内的系统缓存结果
        maximumAge: 5 * 60 * 1000,
        timeout,
      },
    )
  })
    .then((result) => {
      // 统一落缓存：成功写经纬度，失败写不可用标记
      cachedLonLat = result
      if (result) {
        writeSession(KEY_LONLAT, result)
      } else {
        writeSession(KEY_UNAVAILABLE, '1')
      }
      return result
    })
    .finally(() => {
      inFlight = null
    })

  return inFlight
}

/**
 * 清空定位缓存（仅供调试 / 测试使用）。
 * 会同时清空内存与 sessionStorage 缓存，使下次调用重新触发定位。
 */
export function resetGeoCache() {
  cachedLonLat = undefined
  inFlight = null
  deniedToastShown = false
  try {
    sessionStorage.removeItem(KEY_LONLAT)
    sessionStorage.removeItem(KEY_UNAVAILABLE)
  } catch (e) {
    /* 忽略 */
  }
}
