import { expect, test } from "@playwright/test";

test("unauthenticated visitors see the verified access screen", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("VERIFIED ACCESS")).toBeVisible();
  await expect(page.getByLabel("EMAIL ADDRESS")).toBeVisible();
  await expect(page.getByText(/must not be used for operational maneuver decisions/i)).toBeVisible();
});
