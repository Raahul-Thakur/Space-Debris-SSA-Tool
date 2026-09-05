import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure" },
  webServer: {
    command: "node scripts/copy-cesium.mjs && npx next dev -p 3100",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: !process.env.CI,
    env: {
      NEXT_DIST_DIR: ".next-e2e",
      NEXT_PUBLIC_AUTH_TEST_MODE: "unauthenticated"
    }
  }
});
