/* ==========================================================================
   主题读写（PC 管理端）
   - localStorage 键：cd_pc_theme（与 H5 的键隔离）
   - 通过 html.dark class 切换 Element Plus 与自定义 token
   ========================================================================== */

/** 本地存储键 */
export const THEME_KEY = 'cd_pc_theme'

/** 暗色 / 亮色 */
export const THEME_DARK = 'dark'
export const THEME_LIGHT = 'light'

/**
 * 读取已保存的主题；无值时默认暗色（管理端默认暗色，见 ui-design.md §4.3）。
 * @returns {'dark'|'light'}
 */
export function getStoredTheme() {
  const v = localStorage.getItem(THEME_KEY)
  return v === THEME_LIGHT ? THEME_LIGHT : THEME_DARK
}

/**
 * 把主题应用到 <html>（暗色加 .dark，亮色移除）。
 * @param {'dark'|'light'} theme
 */
export function applyTheme(theme) {
  const isDark = theme === THEME_DARK
  document.documentElement.classList.toggle('dark', isDark)
  // 同步移动端浏览器地址栏配色（PC 端无副作用）
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) {
    meta.setAttribute('content', isDark ? '#0F1419' : '#F1F4F6')
  }
}

/**
 * 写入并应用主题。
 * @param {'dark'|'light'} theme
 */
export function setTheme(theme) {
  const normalized = theme === THEME_LIGHT ? THEME_LIGHT : THEME_DARK
  localStorage.setItem(THEME_KEY, normalized)
  applyTheme(normalized)
  return normalized
}

/** 首屏初始化：读取持久化主题并应用（避免闪白 / 闪黑）。 */
export function initTheme() {
  const theme = getStoredTheme()
  applyTheme(theme)
  return theme
}
