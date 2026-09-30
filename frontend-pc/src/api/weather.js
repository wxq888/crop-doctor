import request from './request'

/**
 * 天气端点（既有 weather 模块，见 architecture §3）。
 * 大屏天气面板使用；admin token 亦是合法用户 token，可正常调用。
 */

/**
 * 当前天气。
 * @param {string} [location] 地区（缺省由后端取默认配置）
 * @returns {Promise<object>}
 */
export function getNow(location) {
  const params = location ? { location } : {}
  return request.get('/weather/now', { params })
}

/**
 * 未来数日天气预报。
 * @param {string} [location]
 * @param {number} [days=3]
 * @returns {Promise<object>}
 */
export function getForecast(location, days = 3) {
  const params = { days }
  if (location) params.location = location
  return request.get('/weather/forecast', { params })
}
