/**
 * 时间格式化工具（H5 各页共用）。
 * 后端时间统一为 ISO-8601 UTC，展示规则（适老化：尽量短）：
 * - 今天 → HH:mm
 * - 今年 → MM-DD HH:mm
 * - 跨年 → YYYY-MM-DD
 */

function pad(n) {
  return String(n).padStart(2, '0')
}

/**
 * Date → 'YYYY-MM-DD'（日历筛选回传后端用）。
 * @param {Date} d
 * @returns {string}
 */
export function formatDate(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * ISO 时间 → 简短展示文案；非法/空值返回空串。
 * @param {string|number|Date|null} raw
 * @returns {string}
 */
export function formatDateTime(raw) {
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (sameDay) return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  if (d.getFullYear() === now.getFullYear()) {
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
