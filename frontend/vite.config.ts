import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    watch: {
      // 编辑器/工具写文件时会建临时目录，Windows 下被 watcher 监听到会 EBUSY 崩掉
      ignored: ['**/*.tmpdir/**', '**/*.tmp', '**/.*.tmpdir/**'],
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
