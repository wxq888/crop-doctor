import request from './request'

/**
 * 读取实时事件快照（WS 断线补拉兜底，见 impl-pc-admin-v1 §3.3）。
 * @param {number} [limit=50] 条数，1~100
 * @returns {Promise<{items:object[]}>}
 */
export function getRecentEvents(limit = 50) {
  return request.get('/admin/monitor/events', { params: { limit } })
}
