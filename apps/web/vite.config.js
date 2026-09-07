import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-only health-check endpoints, ported from the old craco/webpack setup
// (plugins/health-check/webpack-health-plugin.js + health-endpoints.js).
//
// The original plugin hooked into webpack's compiler lifecycle
// (compile / done / failed / invalid) plus the webpack Stats API to track
// live build state, error/warning lists and compile timings, then exposed
// that via several endpoints (/health, /health/simple, /health/ready,
// /health/errors, /health/stats).
//
// Vite's dev server has no equivalent to port those endpoints faithfully:
// in dev, Vite transforms modules on demand per-request (no discrete
// "whole app compiled" step the way webpack has), so there is no
// aggregate build/compile state, error list, or warning list to report.
// Reproducing those endpoints would mean guessing at semantics that don't
// exist in Vite, so they were intentionally NOT ported.
//
// TODO: if these are actually needed, consider approximating them using
// Vite's plugin hooks (`transform`, `handleHotUpdate`) and `server.ws`
// error events - but that only captures HMR-time errors, not full parity
// with the old webpack Stats-based reporting. Left for manual follow-up.
//
// Only the genuinely trivial liveness checks are reimplemented below.
function healthCheckPlugin() {
  const enabled = process.env.ENABLE_HEALTH_CHECK === "true";
  if (!enabled) return null;

  const SERVER_START_TIME = Date.now();

  return {
    name: "dev-health-check",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/health/live", (req, res) => {
        res.setHeader("Content-Type", "application/json");
        res.statusCode = 200;
        res.end(
          JSON.stringify({
            alive: true,
            timestamp: new Date().toISOString(),
          }),
        );
      });

      server.middlewares.use("/health", (req, res) => {
        res.setHeader("Content-Type", "application/json");
        res.statusCode = 200;
        res.end(
          JSON.stringify({
            status: "healthy",
            timestamp: new Date().toISOString(),
            uptimeSeconds: Math.floor((Date.now() - SERVER_START_TIME) / 1000),
            note:
              "Simplified for Vite - does not track build/compile state the way the old webpack health plugin did. See TODO in vite.config.js.",
          }),
        );
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), healthCheckPlugin()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    css: true,
  },
});
