import request from './request'

/**
 * 作物分类（由 class-map.json 动态聚合，不写死）。
 * @returns {Promise<{items:Array<{crop_cn:string,crop_en:string,disease_count:number}>}>}
 */
export function getKnowledgeCrops() {
  return request.get('/knowledge/crops')
}

/**
 * 知识文档列表（分页，公开）。
 * @param {{crop?:string,disease?:string,q?:string,page?:number,page_size?:number}} [params]
 * @returns {Promise<{items:Array,total:number,page:number,page_size:number,pages:number}>}
 */
export function listKnowledgeDocs(params = { page: 1, page_size: 10 }) {
  return request.get('/knowledge/docs', { params })
}

/**
 * 知识文档详情（Markdown 正文）。
 * @param {number} id 文档 ID
 * @returns {Promise<object>} KnowledgeDetail
 */
export function getKnowledgeDoc(id) {
  return request.get(`/knowledge/docs/${id}`)
}

/**
 * 门户检索：优先语义（mode=semantic），索引未就绪时回退关键字（mode=keyword）。
 * @param {string} q 查询词
 * @param {number} [topK] 返回条数（1~20，默认 4）
 * @returns {Promise<{items:Array<{doc_id:number|null,slug:string|null,title:string,section:string|null,crop:string|null,disease:string|null,snippet:string|null,score:number|null}>,mode:string}>}
 */
export function searchKnowledge(q, topK = 10) {
  return request.get('/knowledge/search', { params: { q, top_k: topK } })
}
