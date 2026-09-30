/**
 * 天气文字 → emoji 图标映射工具（H5 首页天气卡 / 迷你预报共用）。
 *
 * 设计原则：
 * - 和风天气的文字包含「雷阵雨」「小雨」「雨夹雪」等复合词，故按
 *   「精确匹配 → 关键词包含匹配」两级匹配，关键词数组按优先级从上到下命中即返回；
 * - 任何未知 / 空值都返回 🌍（绝不抛错、绝不出空图标）。
 */

/** 精确匹配表（常见天气文字 → emoji） */
const EXACT_MAP = {
  晴: '☀️',
  多云: '⛅',
  阴: '☁️',
  雾: '🌫️',
  霾: '🌫️',
  雪: '❄️',
  冰雹: '🌨️',
  雷: '⛈️',
  雨: '🌧️',
}

/** 包含匹配规则（按优先级排序：雷 > 雪夹雨 > 雪 > 雨 > 雾霾 > 沙尘 > 多云 > 阴 > 晴） */
const INCLUDE_RULES = [
  { keys: ['雷'], emoji: '⛈️' },
  { keys: ['雪'], emoji: '❄️' },
  { keys: ['雨'], emoji: '🌧️' },
  { keys: ['雾', '霾'], emoji: '🌫️' },
  { keys: ['沙', '尘', '浮尘'], emoji: '🌫️' },
  { keys: ['多云'], emoji: '⛅' },
  { keys: ['阴'], emoji: '☁️' },
  { keys: ['晴'], emoji: '☀️' },
]

/** 未知天气兜底图标 */
const FALLBACK_EMOJI = '🌍'

/**
 * 天气文字 → emoji 图标。
 * @param {string|null|undefined} text 和风天气天气文字（如「多云」「雷阵雨」）
 * @returns {string} 对应 emoji，未知天气返回 🌍
 */
export function weatherEmoji(text) {
  if (!text || typeof text !== 'string') return FALLBACK_EMOJI
  const trimmed = text.trim()
  if (!trimmed) return FALLBACK_EMOJI
  // 1) 精确命中
  if (EXACT_MAP[trimmed]) return EXACT_MAP[trimmed]
  // 2) 包含命中（如「雷阵雨」「小雨」「雨夹雪」）
  for (const rule of INCLUDE_RULES) {
    if (rule.keys.some((k) => trimmed.includes(k))) return rule.emoji
  }
  return FALLBACK_EMOJI
}

export default weatherEmoji
