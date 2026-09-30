<script setup>
/**
 * 暗 / 亮主题切换按钮（答辩投影用亮色，见 ui-design.md §4.3）。
 * 状态存于 stores/theme.js，持久化键 cd_pc_theme。
 */
import { computed } from 'vue'

import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()
const isDark = computed(() => themeStore.isDark)
const text = computed(() => (isDark.value ? '暗色' : '亮色'))
const icon = computed(() => (isDark.value ? '🌙' : '☀️'))

function toggle() {
  themeStore.toggle()
}
</script>

<template>
  <el-button
    class="theme-toggle"
    text
    :title="isDark ? '切换到亮色（答辩投影）' : '切换到暗色'"
    @click="toggle"
  >
    <span class="theme-toggle__icon">{{ icon }}</span>
    <span class="theme-toggle__text">{{ text }}</span>
  </el-button>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--pc-text-muted);
  font-size: 12px;
  padding: 6px 10px;
}
.theme-toggle:hover {
  color: var(--pc-primary);
}
.theme-toggle__icon {
  font-size: 14px;
}
</style>
