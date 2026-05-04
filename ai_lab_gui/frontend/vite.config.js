import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/execute": "http://localhost:8000",
      "/pause": "http://localhost:8000",
      "/resume": "http://localhost:8000",
      "/override": "http://localhost:8000",
      "/status": "http://localhost:8000",
      "/background": "http://localhost:8000",
      "/approve": "http://localhost:8000",
      "/deny": "http://localhost:8000",
      "/approval": "http://localhost:8000",
      "/debug": "http://localhost:8000",
    },
  },
  build: {
    outDir: "../src-tauri/frontend-dist",
    emptyOutDir: true,
  },
});
