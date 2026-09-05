import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Fail rather than silently moving to 5174 when 5173 is taken: the WHOOP
    // redirect URI is registered for one exact origin, so a drifting port
    // breaks the OAuth callback in a way that is tedious to trace back here.
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  // `npm run preview` serves the production build. Pinned for the same reason.
  preview: {
    port: 4173,
    strictPort: true,
  },
});
