import { defineConfig, loadEnv } from "vite";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";

const backend = `http://127.0.0.1:${process.env.PORT_BASE || 8000}`;
const env = loadEnv("development", fileURLToPath(new URL("../", import.meta.url)), "SITE_");
const siteTimeZone = process.env.SITE_TIMEZONE || env.SITE_TIMEZONE || "Europe/Berlin";

export default defineConfig({
  plugins: [react(), {
    name: "site-calendar",
    apply: "serve",
    transformIndexHtml: () => [{ tag: "meta", attrs: { name: "site-timezone", content: siteTimeZone }, injectTo: "head" }],
  }],
  server: {
    proxy: {
      "/api": backend,
      "/media": backend,
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
