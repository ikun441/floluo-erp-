import { defineConfig } from "@playwright/test";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "../..");
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 30000,
  expect: { timeout: 10000 },
  outputDir: path.join(root, "output/playwright/test-results"),
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3000",
    viewport: { width: 1440, height: 1000 },
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
      args: ["--enable-unsafe-swiftshader"],
    },
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "../../.venv/bin/python serve.py",
      cwd: import.meta.dirname,
      url: "http://127.0.0.1:8000/health/ready",
      reuseExistingServer: process.env.ERP_REUSE_TEST_SERVERS === "1",
      timeout: 30000,
    },
    {
      command: "npm run start",
      cwd: path.join(root, "frontend"),
      url: "http://127.0.0.1:3000",
      reuseExistingServer: process.env.ERP_REUSE_TEST_SERVERS === "1",
      timeout: 30000,
    },
  ],
});
