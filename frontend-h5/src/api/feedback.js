import request from './request'

/**
 * 创建反馈工单。
 * @param {{
 *   type:'question'|'result_verdict',
 *   title:string,
 *   content:string,
 *   record_id?:number|null,
 *   verdict?:'correct'|'wrong'|'unsure'|null,
 *   correct_disease?:string|null
 * }} payload FeedbackCreate
 * @returns {Promise<object>} FeedbackOut
 */
export function createFeedback(payload) {
  return request.post('/feedback', payload)
}

/**
 * 我的工单列表（分页）。
 * @param {{page?:number,page_size?:number,status?:string,type?:string}} [params]
 * @returns {Promise<{items:Array,total:number,page:number,page_size:number,pages:number}>}
 */
export function listMyFeedbacks(params = { page: 1, page_size: 10 }) {
  return request.get('/feedback/mine', { params })
}

/**
 * 工单详情（含多轮消息；打开即把 admin 消息置已读）。
 * @param {number} id 工单 ID
 * @returns {Promise<object>} FeedbackDetail
 */
export function getFeedbackDetail(id) {
  return request.get(`/feedback/${id}`)
}

/**
 * 用户追问（多轮往来）。
 * @param {number} id 工单 ID
 * @param {string} content 消息正文
 * @returns {Promise<object>} FeedbackMessageOut
 */
export function sendFeedbackMessage(id, content) {
  return request.post(`/feedback/${id}/messages`, { content })
}

/**
 * 显式置已读（打开详情会自动置读，此接口用于手动兜底）。
 * @param {number} id 工单 ID
 */
export function markFeedbackRead(id) {
  return request.post(`/feedback/${id}/read`)
}

/**
 * 我的未读回复数（admin 回复且未读的条数）。
 * @returns {Promise<{count:number}>}
 */
export function getFeedbackUnreadCount() {
  return request.get('/feedback/unread-count')
}
