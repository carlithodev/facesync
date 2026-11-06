 import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Config Vite para Tauri con React + Tailwind v4.
// - Puerto fijo 1420 (el que espera tauri.conf.json -> devUrl).
// - No limpiar la consola para no tapar los logs de Tauri/Rust.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
});
