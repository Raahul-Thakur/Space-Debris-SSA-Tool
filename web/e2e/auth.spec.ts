import { expect, test } from "@playwright/test";

/**
 * The console is readable without an account.
 *
 * These run with NEXT_PUBLIC_AUTH_TEST_MODE=unauthenticated and no API
 * behind them, so the assertions deliberately cover the shell rather than
 * any data: what matters here is that a visitor reaches the picture at all,
 * which is what the previous version of this file asserted the opposite of.
 */

test("a visitor without an account reaches the console, not a wall", async ({
  page
}) => {
  await page.goto("/");

  await expect(page.getByText("ORBITAL PICTURE / +3H")).toBeVisible();
  await expect(page.getByLabel("Operator command")).toBeVisible();
  // The sign-in form belongs on its own page, not in front of this one.
  await expect(page.getByLabel("EMAIL ADDRESS")).toHaveCount(0);
});

test("signing in is offered rather than imposed", async ({ page }) => {
  await page.goto("/");

  // Scoped to the topbar: the guest empty states offer sign-in too, which is
  // intended, so an unscoped match finds four links.
  const signIn = page
    .locator("header")
    .getByRole("link", { name: /sign in/i });
  await expect(signIn).toBeVisible();
  await signIn.click();

  await expect(page).toHaveURL(/\/signin$/);
  await expect(page.getByText("VERIFIED ACCESS")).toBeVisible();
  await expect(page.getByLabel("EMAIL ADDRESS")).toBeVisible();
});

test("the sign-in page carries the limitations notice and a way back", async ({
  page
}) => {
  await page.goto("/signin");

  await expect(
    page.getByText(/must not be used for operational maneuver decisions/i)
  ).toBeVisible();

  await page.getByRole("link", { name: /back to the public picture/i }).click();
  await expect(page).toHaveURL(/\/$/);
});

test("attempting a command sends a signed-out visitor to sign in", async ({
  page
}) => {
  await page.goto("/");

  await page.getByLabel("Operator command").fill("screen 25544");
  await page.getByRole("button", { name: /execute/i }).click();

  // The prompt arrives at the point of action, and the command is not lost.
  await expect(page).toHaveURL(/\/signin$/);
  const pending = await page.evaluate(() =>
    window.sessionStorage.getItem("astra.pending-command")
  );
  expect(pending).toBe("screen 25544");
});

test("the account page is not reachable without an account", async ({ page }) => {
  // It shows a plan, usage figures and run history. None of that exists for
  // a visitor, and rendering an empty shell would imply it did.
  await page.goto("/account");
  await expect(page).toHaveURL(/\/signin$/);
});
