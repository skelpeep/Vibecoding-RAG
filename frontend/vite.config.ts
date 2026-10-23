import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const apiTarget = process.env.KB_API_TARGET || 'http://127.0.0.1:8105'
export default defineConfig({
  plugins: [vue()],
  server: { port: 5186, strictPort: true, proxy: { '/api': { target: apiTarget, changeOrigin: true } } },
  preview: { port: 4173, strictPort: true, proxy: { '/api': { target: apiTarget, changeOrigin: true } } },
})
