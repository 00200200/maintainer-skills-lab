import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Checked-in production assets let Python serve Studio without Node at runtime.
  build: { outDir: 'static', sourcemap: false },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        // The backend checks Host against its own local address and port.
        changeOrigin: true,
      },
    },
  },
});
