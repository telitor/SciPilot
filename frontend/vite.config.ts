import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const normalizedId = id.replaceAll('\\', '/');

          if (normalizedId.includes('/node_modules/zrender/')) {
            return 'echarts-renderer';
          }

          if (normalizedId.includes('/node_modules/echarts/')) {
            return 'echarts-core';
          }

          if (
            normalizedId.includes('/node_modules/echarts-for-react/')
            || normalizedId.includes('/node_modules/size-sensor/')
          ) {
            return 'echarts-react';
          }

          if (
            normalizedId.includes('/node_modules/react/')
            || normalizedId.includes('/node_modules/react-dom/')
            || normalizedId.includes('/node_modules/react-router/')
            || normalizedId.includes('/node_modules/react-router-dom/')
            || normalizedId.includes('/node_modules/scheduler/')
          ) {
            return 'vendor';
          }

          if (
            normalizedId.includes('/node_modules/react-markdown/')
            || normalizedId.includes('/node_modules/remark-')
            || normalizedId.includes('/node_modules/rehype-')
            || normalizedId.includes('/node_modules/katex/')
          ) {
            return 'markdown';
          }
        },
      },
    },
  },
})
