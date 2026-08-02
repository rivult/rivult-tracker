import { defineConfig } from "vitest/config";

// Pure-function tests only — a plain node environment (no jsdom, no Tailwind
// plugin) keeps them fast and free of the app's vite plugins.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
