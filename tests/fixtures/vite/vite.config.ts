// vite.config.ts of a typical React app; never executed by worktree-shield.
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/* An old port, commented out:
   server: { port: 3000 },
*/
export default defineConfig({
  plugins: [react()],
  cacheDir: '/tmp/vite-cache-shared',
  server: {
    host: '127.0.0.1',
    port: 5173, // the dev server
    strictPort: true,
    hmr: { port: 24678 },
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
  },
  build: {
    outDir: '/srv/www/app',
  },
  define: { __URL__: JSON.stringify("server: { port: 9999 }") },
})
