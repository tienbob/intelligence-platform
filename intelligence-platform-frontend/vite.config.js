import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // In local dev, proxy API calls to the Rails gateway (port 3000).
      // Rails authenticates, authorizes, and forwards to the Python service.
      // In Docker, nginx handles this — this proxy is only for `npm run dev`.
      '/api': {
        target: 'http://localhost:3000',
        changeOrigin: true,
      },
    },
  },
})
