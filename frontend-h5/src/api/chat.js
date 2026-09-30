import request from './request'

/** API 基础地址（SSE 端点同样走它，见 utils/sse.js） */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

/** 静态资源基地址（后端出参为 `/static/...`，需与静态基址拼接） */
export const STATIC_BASE_URL = import.meta.env.VITE_STATIC_BASE_URL

/**
 * 拼装静态资源完整 URL。
 * @param {string|null|undefined} path 后端返回的 `/static/...` 路径
 * @returns {string} 完整 URL；path 为空时返回空串
 */
export function resolveStaticUrl(path) {
  if (!path) return ''
  if (/^https?:\/\//i.test(path)) return path
  return `${STATIC_BASE_URL}${path}`
}

// chineseNameHint 保留：真实中文名由后端 detection_context 提供，前端不复制映射表

/**
 * 创建会话。
 * @param {number|null} detectionId 可空；携带则注入检测上下文
 * @param {string|null} title 可空；缺省由后端生成
 * @returns {Promise<object>} ChatSessionOut
 */
export function createSession(detectionId = null, title = null) {
  const body = {}
  if (detectionId != null) body.detection_id = detectionId
  if (title) body.title = title
  return request.post('/chat/sessions', body)
}

/**
 * 会话列表（分页）。
 * @param {{page?:number,page_size?:number}} params
 * @returns {Promise<{items:Array,total:number,page:number,page_size:number,pages:number}>}
 */
export function listSessions(params = { page: 1, page_size: 50 }) {
  return request.get('/chat/sessions', { params })
}

/**
 * 会话详情（含检测上下文 detection_context）。
 * @param {number} id 会话 ID
 * @returns {Promise<object>} ChatSessionDetailOut
 */
export function getSession(id) {
  return request.get(`/chat/sessions/${id}`)
}

/**
 * 会话消息（后端按时间倒序分页，前端需反转为正序渲染）。
 * @param {number} id 会话 ID
 * @param {{page?:number,page_size?:number}} params
 * @returns {Promise<{items:Array,total:number}>}
 */
export function getMessages(id, params = { page: 1, page_size: 100 }) {
  return request.get(`/chat/sessions/${id}/messages`, { params })
}

/**
 * 删除会话（消息级联删除）。
 * @param {number} id 会话 ID
 */
export function deleteSession(id) {
  return request.delete(`/chat/sessions/${id}`)
}

/**
 * 构造「指定会话发消息」的 SSE 端点 URL。
 * @param {number} sessionId
 * @returns {string}
 */
export function messagesSseUrl(sessionId) {
  return `${API_BASE_URL}/chat/sessions/${sessionId}/messages`
}

/**
 * 构造「自动建会话提问」的 SSE 端点 URL。
 * @returns {string}
 */
export function askSseUrl() {
  return `${API_BASE_URL}/chat/ask`
}
