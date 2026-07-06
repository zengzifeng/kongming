import http from 'node:http';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendTarget = 'http://127.0.0.1:5001';
const ipv4Agent = new http.Agent({ family: 4 });

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: backendTarget,
        agent: ipv4Agent,
        changeOrigin: true,
        secure: false,
      },
      '/healthz': {
        target: backendTarget,
        agent: ipv4Agent,
        changeOrigin: true,
        secure: false,
      },
      '/readyz': {
        target: backendTarget,
        agent: ipv4Agent,
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
