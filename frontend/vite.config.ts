import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The FlintGraph API does not send CORS headers, so we proxy same-origin requests
// from the dev server to the backend. The browser only ever talks to Vite.
// Override the backend location with FLINT_GRAPH_API_TARGET if it is not on :8000.
const API_TARGET = process.env.FLINT_GRAPH_API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: API_TARGET,
        changeOrigin: true,
        // Do not buffer Server-Sent Events (the query stream).
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            if (proxyRes.headers["content-type"]?.includes("text/event-stream")) {
              proxyRes.headers["cache-control"] = "no-cache";
            }
          });
        },
      },
      "/health": { target: API_TARGET, changeOrigin: true },
    },
  },
});
