import request from './request'
import { resolveStaticUrl } from './chat'

/**
 * 获取某条检测记录详情。
 *
 * 说明：design §3.6 的 api 清单为 request/auth/chat 三个文件；但「检测上下文卡片」
 * 的数据来源是 `GET /detection/records/{id}`（team-lead 明确指示），故单独拆出
 * detection.js，避免把 detection 逻辑塞进 chat.js 造成职责混淆。
 *
 * @param {number} recordId 检测记录 ID
 * @returns {Promise<object>} DetectionDetailOut
 */
export function getDetectionRecord(recordId) {
  return request.get(`/detection/records/${recordId}`)
}

/**
 * 查询某条检测记录的热力图状态。
 * @param {number} recordId 检测记录 ID
 * @returns {Promise<{status:'pending'|'done'|'failed'|'skipped',url?:string}>}
 */
export function getDetectionGradcam(recordId) {
  return request.get(`/detection/records/${recordId}/gradcam`)
}

/**
 * 上传图片创建检测（multipart）。同步链路：推理数百 ms 后直接返回结论。
 * @param {File} file 图片文件（jpeg/png/webp，≤10MB）
 * @param {{location?:string,conf?:number|null}} [options] 可选定位与置信度阈值
 * @returns {Promise<object>} DetectionRecordOut
 */
export function uploadDetectionImage(file, options = {}) {
  const { location = '', conf = null } = options
  const fd = new FormData()
  fd.append('file', file)
  if (location) fd.append('location', location)
  if (conf != null) fd.append('conf', String(conf))
  // 推理耗时高于常规请求，单独放宽超时
  return request.post('/detection/image', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  })
}

/**
 * 我的检测记录（分页，强制 user_id 过滤）。
 * @param {{page?:number,page_size?:number,disease?:string,severity_level?:number,crop?:string,start?:string,end?:string}} [params]
 * @returns {Promise<{items:Array,total:number,page:number,page_size:number,pages:number}>}
 */
export function listDetectionRecords(params = { page: 1, page_size: 10 }) {
  return request.get('/detection/records', { params })
}

/**
 * 删除某条检测记录（明细级联删除）。
 * @param {number} recordId 检测记录 ID
 */
export function deleteDetectionRecord(recordId) {
  return request.delete(`/detection/records/${recordId}`)
}

export { resolveStaticUrl }
