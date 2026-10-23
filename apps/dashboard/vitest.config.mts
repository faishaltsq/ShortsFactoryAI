import { defineConfig } from "vitest/config";
import path from "node:path";

// Shell di mesin ini mengekspor NODE_ENV=production, yang membuat React ter-resolve
// ke build produksi tanpa act(). Vitest butuh build development, jadi paksa di sini
// sebelum modul apa pun di-resolve.
process.env.NODE_ENV = "test";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test-setup.ts"],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
    // React 19 hanya mengekspos act() pada build development.
    conditions: ["development"],
  },
});
