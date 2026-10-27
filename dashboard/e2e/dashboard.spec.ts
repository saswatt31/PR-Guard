import { expect, test } from "@playwright/test";

test("overview renders statistics and filters the run table", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: /Proof, not promises/ })).toBeVisible();
  await expect(page.getByText("acme/demo")).toBeVisible();
  await expect(page.getByText("beta/stale")).toBeVisible();
  await expect(page.getByText("acme/api")).toBeVisible();
  await expect(page.getByText("Newest webhook-triggered runs first")).toBeVisible();

  await page.getByLabel("Status").selectOption("failed");
  await page.getByRole("button", { name: "Filter" }).click();

  await expect(page).toHaveURL(/status=failed/);
  await expect(page.getByText("1 matching run")).toBeVisible();
  await expect(page.getByText("beta/stale")).toBeVisible();
  await expect(page.getByRole("link", { name: "acme/demo" })).toHaveCount(0);

  await page.getByRole("link", { name: "Clear" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("link", { name: "acme/demo" })).toBeVisible();
});

test("run detail exposes verified tests, evidence, review and metadata", async ({ page }) => {
  await page.goto("/runs/run-verified-1");

  await expect(page.getByRole("heading", { level: 1, name: "acme/demo" })).toBeVisible();
  await expect(page.getByText("1 verified, 1 not verified")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Verified tests" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Not verified" })).toBeVisible();
  await expect(page.getByText("sandbox test failed")).toBeVisible();

  await page.getByText("src/math.test.ts · add").click();
  await expect(page.getByText("it('adds', () => expect(add(1, 2)).toBe(3));")).toBeVisible();

  await expect(page.getByText("npx vitest run --coverage")).toBeVisible();
  await page.getByText("View captured output").click();
  await expect(page.getByText("Test Files  1 passed")).toBeVisible();

  await expect(page.getByText("No blocking issues.")).toBeVisible();
  await expect(page.getByText("Agent trace")).toBeVisible();
  await expect(page.getByText(/max_tests/)).toBeVisible();
});

test("unknown run renders a 404 page", async ({ page }) => {
  await page.goto("/runs/missing");

  await expect(page.getByRole("heading", { level: 1, name: "No such run." })).toBeVisible();
  // Dynamic routes stream the loading shell before notFound() runs, so Next.js
  // reports HTTP 200 with a noindex hint instead of a 404 status.
  await expect(page.locator('meta[name="robots"]').first()).toHaveAttribute(
    "content",
    "noindex",
  );
});
