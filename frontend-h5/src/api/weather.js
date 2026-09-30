import request from './request'

/**
 * 查询施药时机建议（含未来降雨窗口）。
 * 天气服务任何异常均降级返回（degraded=true / data=null），不抛错。
 * @param {string} [location] 可选位置，缺省用后端配置
 * @returns {Promise<{advice:string,next_rain_date?:string|null,degraded?:boolean}|null>}
 */
export function getSprayAdvice(location = '') {
  const params = location ? { location } : {}
  return request.get('/weather/spray-advice', { params })
}

/**
 * 实时天气（和风天气实况）。
 * 数据不可用时后端降级返回 `{degraded:true}` 且字段为 null，不抛错。
 * @param {string} [location] 可选位置，形如 `"经度,纬度"`，缺省用后端配置
 * @returns {Promise<{text:string,temp:number,humidity:number,windDir:string,
 *   windScale:number,feelsLike:number,precip:number,obsTime:string,degraded:boolean}|null>}
 */
export function getNow(location = '') {
  const params = location ? { location } : {}
  return request.get('/weather/now', { params })
}

/**
 * 未来 N 天（最多 7 天；≤3 天走和风 3d，>3 天走和风 7d）天气预报。
 * 数据不可用时后端降级返回 `{list:[], degraded:true}`，不抛错。
 * @param {string} [location] 可选位置，形如 `"经度,纬度"`，缺省用后端配置
 * @param {number} [days=3] 预报天数（1~7）
 * @returns {Promise<{list:Array<{date:string,temp_min:number,temp_max:number,
 *   text_day:string,text_night:string,humidity:number,precip:number}>,degraded:boolean}|null>}
 */
export function getForecast(location = '', days = 3) {
  const params = { days }
  if (location) params.location = location
  return request.get('/weather/forecast', { params })
}

/**
 * 未来 24 小时逐时预报（含降水概率 pop）。
 * 数据不可用时后端降级返回 `{list:[], degraded:true}`，不抛错。
 * @param {string} [location] 可选位置，形如 `"经度,纬度"`，缺省用后端配置
 * @returns {Promise<{list:Array<{fx_time:string,temp:number,text:string,
 *   humidity:number,precip:number,pop:number,wind_dir:string,wind_scale:string}>,
 *   degraded:boolean}|null>}
 */
export function getHourly(location = '') {
  const params = location ? { location } : {}
  return request.get('/weather/hourly', { params })
}
