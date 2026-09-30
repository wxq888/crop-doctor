import request from './request'

/**
 * feedback 模块端点（见 impl-pc-admin-v1 §2.4）。
 * 含 H5 用户侧与 PC 管理员侧（admin）两条线；PC 管理端主要用 admin 侧。
 */

/* ---------------- H5 用户侧 ---------------- */

/** 创建工单 */
export function createFeedback(payload) {
  return request.post('/feedback', payload)
}

/** 我的工单列表 */
export function getMyFeedbacks(params = {}) {
  return request.get('/feedback/mine', { params })
}

/** 工单详情（自动把 admin 消息置已读） */
export function getFeedbackDetail(id) {
  return request.get(`/feedback/${id}`)
}

/** 用户追问 */
export function addFeedbackMessage(id, content) {
  return request.post(`/feedback/${id}/messages`, { content })
}

/** 显式置已读 */
export function readFeedback(id) {
  return request.post(`/feedback/${id}/read`)
}

/** 用户未读数 */
export function getUnreadCount() {
  return request.get('/feedback/unread-count')
}

/* ---------------- PC 管理员侧 ---------------- */

/**
 * 工单列表（管理员）。
 * @param {{page?:number,page_size?:number,status?:string,type?:string,keyword?:string,unread_only?:boolean}} params
 */
export function getAdminFeedbacks(params = {}) {
  return request.get('/admin/feedback', { params })
}

/** 工单详情（管理员，自动把 user 消息置已读） */
export function getAdminFeedbackDetail(id) {
  return request.get(`/admin/feedback/${id}`)
}

/** 管理员回复 */
export function adminReplyFeedback(id, content) {
  return request.post(`/admin/feedback/${id}/reply`, { content })
}

/** 管理员关闭工单（终态） */
export function adminCloseFeedback(id) {
  return request.post(`/admin/feedback/${id}/close`)
}

/** 管理员未读数（导航角标） */
export function getAdminUnreadCount() {
  return request.get('/admin/feedback/unread-count')
}
