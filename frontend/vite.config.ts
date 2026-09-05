import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3001,
    // Fail rather than silently moving to the next free port: the WHOOP
    // redirect URI is registered for one exact origin, so a drifting port
    // breaks the OAuth callback in a way that is tedious to trace back here.
    strictPort: true,
    // Only development runs two servers. The production image serves the
    // built app from the API itself, on one port and one origin.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
  // `npm run preview` serves the production build. Pinned for the same reason.
  preview: {
    port: 3002,
    strictPort: true,
  },
});
