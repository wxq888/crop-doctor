import { defineStore } from 'pinia'

import { getStoredTheme, setTheme as persistTheme } from '@/utils/theme'

/**
 * 主题状态：暗色（默认）/ 亮色，切换动作写入 localStorage（cd_pc_theme）。
 */
export const useThemeStore = defineStore('theme', {
  state: () => ({
    /** 当前主题：'dark' | 'light' */
    theme: getStoredTheme(),
  }),

  getters: {
    /** 是否暗色 */
    isDark: (state) => state.theme === 'dark',
  },

  actions: {
    /**
     * 设置主题。
     * @param {'dark'|'light'} theme
     */
    setTheme(theme) {
      this.theme = persistTheme(theme)
    },

    /** 在暗色 / 亮色之间切换 */
    toggle() {
      this.setTheme(this.theme === 'dark' ? 'light' : 'dark')
    },
  },
})
