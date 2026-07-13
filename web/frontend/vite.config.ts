import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;

          if (
            id.includes("/leaflet/") ||
            id.includes("/react-leaflet/") ||
            id.includes("/@react-leaflet/") ||
            id.includes("leaflet-imageoverlay-rotated")
          ) {
            return "map";
          }

          if (
            id.includes("/react-markdown/") ||
            id.includes("/remark-") ||
            id.includes("/micromark") ||
            id.includes("/mdast-") ||
            id.includes("/unist-")
          ) {
            return "markdown";
          }

          if (id.includes("/react-dom/") || id.includes("/react/")) {
            return "react";
          }
        },
      },
    },
  },
});
