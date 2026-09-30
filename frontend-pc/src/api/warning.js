import request from './request'

/**
 * warning 模块端点（见 impl-pc-admin-v1 §2.3）。
 * H5 用 /warning/alerts（本人+全局）；PC 预警记录用 /warning/records（admin 全量）。
 */

/** H5 我的预警列表 */
export function getAlerts(params = {}) {
  return request.get('/warning/alerts', { params })
}

/** H5 预警未读数 */
export function getAlertsUnreadCount() {
  return request.get('/warning/alerts/unread-count')
}

/** H5 标记预警已读 */
export function readAlert(id) {
  return request.post(`/warning/alerts/${id}/read`)
}

/* ---------------- PC 管理员侧 ---------------- */

/**
 * 规则列表。
 * @param {{page?:number,page_size?:number,enabled?:boolean,disease?:string}} params
 */
export function getRules(params = {}) {
  return request.get('/warning/rules', { params })
}

/**
 * 新建规则。
 * @param {{disease:string,crop?:string,temp_min?:number,temp_max?:number,humidity_min?:number,humidity_max?:number,rain_condition:string,risk_level:string,advice?:string,enabled:boolean}} payload
 */
export function createRule(payload) {
  return request.post('/warning/rules', payload)
}

/** 更新规则（可部分字段） */
export function updateRule(id, payload) {
  return request.put(`/warning/rules/${id}`, payload)
}

/** 删除规则 */
export function deleteRule(id) {
  return request.delete(`/warning/rules/${id}`)
}

/**
 * 风险总览（含 degraded 降级标记）。
 * @param {string} [location]
 */
export function getOverview(location) {
  const params = location ? { location } : {}
  return request.get('/warning/overview', { params })
}

/**
 * 手动触发风险引擎评估。
 * @param {string} [location]
 */
export function refreshWarning(location) {
  return request.post('/warning/refresh', location ? { location } : {})
}

/**
 * 预警记录列表（admin 全量）。
 * @param {{page?:number,page_size?:number,risk_level?:string,source?:string,location?:string,start?:string,end?:string}} params
 */
export function getRecords(params = {}) {
  return request.get('/warning/records', { params })
}
