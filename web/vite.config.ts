import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Le build est écrit directement dans server/static : FastAPI le sert tel quel (Electron, Docker, web).
// En développement (« npm run dev »), les appels /api sont envoyés à un serveur BookReader déjà lancé
// (par défaut le conteneur Docker sur le port 8001 ; changer avec API_URL).
export default defineConfig({
  plugins: [svelte()],
  build: { outDir: '../server/static', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { '/api': process.env.API_URL ?? 'http://127.0.0.1:8001' },
  },
});
