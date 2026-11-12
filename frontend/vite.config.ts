import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const backend = process.env.WORKSPACE_BACKEND ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": backend,
      "/health": backend,
      "/ws": { target: backend.replace("http", "ws"), ws: true },
    },
  },
  build: {
    target: "safari16",
    chunkSizeWarningLimit: 4000,
  },
  test: { environment: "jsdom" },
});
