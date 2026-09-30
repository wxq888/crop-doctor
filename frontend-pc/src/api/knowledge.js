import request from './request'

/**
 * knowledge 模块端点（见 impl-pc-admin-v1 §2.5）。
 * 门户（router，公开）+ admin 管理（admin_router，/admin/knowledge）。
 */

/* ---------------- 门户（公开） ---------------- */

/** 作物分类（由 class-map.json 动态聚合） */
export function getCrops() {
  return request.get('/knowledge/crops')
}

/**
 * 文档列表。
 * @param {{crop?:string,disease?:string,q?:string,page?:number,page_size?:number}} params
 */
export function getDocs(params = {}) {
  return request.get('/knowledge/docs', { params })
}

/** 文档详情 */
export function getDocDetail(id) {
  return request.get(`/knowledge/docs/${id}`)
}

/**
 * 语义 / 关键字搜索。
 * @param {string} q
 * @param {number} [topK=4]
 */
export function searchKnowledge(q, topK = 4) {
  return request.get('/knowledge/search', { params: { q, top_k: topK } })
}

/* ---------------- PC 管理员侧 ---------------- */

/**
 * 管理端文档列表（额外支持 vector_status 过滤）。
 * @param {{crop?:string,disease?:string,q?:string,vector_status?:string,page?:number,page_size?:number}} params
 */
export function getAdminDocs(params = {}) {
  return request.get('/admin/knowledge/docs', { params })
}

/**
 * 新建文档：支持 multipart（file=.md）或 JSON（{title,crop,disease,content_md,slug}）。
 * @param {FormData|object} payload
 */
export function createDoc(payload) {
  if (payload instanceof FormData) {
    return request.post('/admin/knowledge/docs', payload, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  }
  return request.post('/admin/knowledge/docs', payload)
}

/**
 * 更新文档。
 * @param {number} id
 * @param {{title?:string,crop?:string,disease?:string,content_md?:string}} payload
 */
export function updateDoc(id, payload) {
  return request.put(`/admin/knowledge/docs/${id}`, payload)
}

/** 删除文档 */
export function deleteDoc(id) {
  return request.delete(`/admin/knowledge/docs/${id}`)
}

/** 触发重新向量化（后台任务） */
export function reindex() {
  return request.post('/admin/knowledge/reindex')
}

/** 查询重新向量化状态 */
export function getReindexStatus() {
  return request.get('/admin/knowledge/reindex/status')
}
