import request from './request'

/**
 * 预警消息列表（本人 + 全局广播，分页）。
 * @param {{page?:number,page_size?:number,risk_level?:string,unread_only?:boolean}} [params]
 * @returns {Promise<{items:Array,total:number,page:number,page_size:number,pages:number}>}
 */
export function listAlerts(params = { page: 1, page_size: 10 }) {
  return request.get('/warning/alerts', { params })
}

/**
 * 预警未读数。
 * @returns {Promise<{count:number}>}
 */
export function getAlertUnreadCount() {
  return request.get('/warning/alerts/unread-count')
}

/**
 * 单条预警置已读。
 * @param {number} id 预警记录 ID
 */
export function markAlertRead(id) {
  return request.post(`/warning/alerts/${id}/read`)
}
