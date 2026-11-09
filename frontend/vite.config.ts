import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: { manualChunks: { fluent: ["@fluentui/react-components", "@fluentui/react-icons"] } },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:18000",
      "/v1": "http://localhost:18000",
      "/docs": "http://localhost:18000",
      "/openapi.json": "http://localhost:18000",
    },
  },
});
