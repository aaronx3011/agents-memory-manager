import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: ".", testMatch: "*.spec.js", workers: 1,
  use: { baseURL: process.env.MEMORY_URL || "http://127.0.0.1:8765", headless: true },
  reporter: "list",
});
