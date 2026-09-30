import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Vite 配置：Vue3 单文件组件 + `@` 别名 + 本地开发服务器
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      // 源码根别名，避免深层相对路径
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    // PC 管理端与 H5（5173）区分端口，避免同时调试冲突
    port: 5175,
    strictPort: false,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // 大屏含 ECharts，包体较大，放宽告警阈值
    chunkSizeWarningLimit: 2000,
  },
})
