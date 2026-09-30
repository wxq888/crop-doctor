import request from './request'

/**
 * admin 模块全部端点（见 impl-pc-admin-v1 §2.1）。
 * T04 一次性写全，供大屏（Dashboard）与 T05 各页面只读复用。
 */

/**
 * 统计概览（今日检测 / 今日新增用户 / 总用户 / 总检测 / 今日健康率 / 今日平均置信度 / 生效预警 / 待回复工单）。
 * @returns {Promise<{today_detections:number,today_new_users:number,total_users:number,total_detections:number,today_healthy_rate:number,today_avg_conf:number,warnings_active:number,pending_feedbacks:number}>}
 */
export function getStatsOverview() {
  return request.get('/admin/stats/overview')
}

/**
 * 统计趋势（近 N 日检测量 / 健康数 / 预警数 / 患病率排行 / 严重度分布 / 按作物分布）。
 * @param {number} [days=7] 天数，1~30
 * @returns {Promise<object>}
 */
export function getStatsTrend(days = 7) {
  return request.get('/admin/stats/trend', { params: { days } })
}

/**
 * 全局检测记录分页查询（admin 可见所有用户）。
 * @param {{page?:number,page_size?:number,user_id?:number,disease?:string,severity_level?:number,crop?:string,start?:string,end?:string,has_feedback?:boolean}} params
 * @returns {Promise<{items:object[],total:number,page:number,page_size:number,pages:number}>}
 */
export function getDetections(params = {}) {
  return request.get('/admin/detections', { params })
}

/**
 * 全局检测记录详情。
 * @param {number} id
 * @returns {Promise<object>}
 */
export function getDetectionDetail(id) {
  return request.get(`/admin/detections/${id}`)
}

/**
 * 用户列表分页查询。
 * @param {{page?:number,page_size?:number,keyword?:string,role?:string,status?:number}} params
 * @returns {Promise<object>}
 */
export function getUsers(params = {}) {
  return request.get('/admin/users', { params })
}

/**
 * 用户详情（含检测 / 反馈 / 预警三类记录）。
 * @param {number} id
 * @returns {Promise<object>}
 */
export function getUserDetail(id) {
  return request.get(`/admin/users/${id}`)
}

/**
 * 启用 / 禁用用户。
 * @param {number} id
 * @param {0|1} status 1=启用 0=禁用
 * @returns {Promise<object>}
 */
export function updateUserStatus(id, status) {
  return request.put(`/admin/users/${id}/status`, { status })
}

/**
 * 重置用户密码。
 * @param {number} id
 * @param {string} [newPassword] 不传则由后端生成
 * @returns {Promise<{username:string,new_password:string}>}
 */
export function resetUserPassword(id, newPassword) {
  const payload = newPassword ? { new_password: newPassword } : {}
  return request.post(`/admin/users/${id}/reset-password`, payload)
}

/**
 * 模型权重列表 + 当前生效 + 已加载状态。
 * @returns {Promise<{items:object[],active:string,loaded:boolean}>}
 */
export function getModels() {
  return request.get('/admin/model')
}

/**
 * 切换生效模型（CPU 热加载，接口耗时数秒）。
 * @param {string} filename
 * @returns {Promise<object>}
 */
export function activateModel(filename) {
  return request.post('/admin/model/activate', { filename })
}
