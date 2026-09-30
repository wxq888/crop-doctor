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
    port: 5173,
    // H5 调试：允许局域网真机访问时改成 0.0.0.0（后端 CORS 已放开）
    strictPort: false,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
  },
})
