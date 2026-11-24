import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /ws is proxied to the Python bridge (python -m jarvis_os --no-window).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/ws": { target: "ws://127.0.0.1:8765", ws: true } } },
  build: { chunkSizeWarningLimit: 1600 },
});
