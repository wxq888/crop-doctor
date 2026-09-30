/* ==========================================================================
   静态资源 URL 拼装（图片走 VITE_STATIC_BASE_URL，见 impl-pc-admin-v1 §12.9）
   ========================================================================== */

const STATIC_BASE = import.meta.env.VITE_STATIC_BASE_URL || ''

/**
 * 把后端返回的图片相对路径拼成可访问 URL。
 * - 已是 http(s) 绝对地址：原样返回
 * - 空值：返回空串（由调用方展示占位）
 * @param {string} [path]
 * @returns {string}
 */
export function assetUrl(path) {
  if (!path) return ''
  if (/^https?:\/\//i.test(path) || path.startsWith('data:')) return path
  const base = STATIC_BASE.replace(/\/+$/, '')
  const rel = String(path).replace(/^\/+/, '')
  return `${base}/${rel}`
}
