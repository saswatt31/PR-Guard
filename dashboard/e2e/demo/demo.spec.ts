import { expect, test } from "@playwright/test";

test("demo journey works with no backend and no mock API", async ({ page }) => {
  const backendCalls: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/") || url.port === "8000" || url.port === "9") {
      backendCalls.push(request.url());
    }
  });

  await page.goto("/");

  const banner = page.getByTestId("demo-banner");
  await expect(banner).toContainText(
    "Demo mode: replaying recorded results from real runs",
  );
  await expect(banner).toContainText("FakeLLM");
  await expect(banner).toContainText("LocalSandboxRunner");
  await expect(page.getByText("Recorded · read only").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "acme/prguard-demo" })).toBeVisible();
  await expect(page.getByText("Newest webhook-triggered runs first")).toBeVisible();

  await page.getByLabel("Status").selectOption("succeeded");
  await page.getByRole("button", { name: "Filter" }).click();
  await expect(page).toHaveURL(/status=succeeded/);
  await expect(page.getByText("1 matching run")).toBeVisible();

  await page.getByRole("link", { name: "acme/prguard-demo" }).click();
  await expect(page).toHaveURL(/\/runs\//);
  await expect(page.getByTestId("demo-detail-note")).toContainText("FakeLLM");
  await expect(page.getByText("Open PR unavailable")).toHaveAttribute(
    "aria-disabled",
    "true",
  );
  await expect(page.getByRole("heading", { name: "Verified tests" })).toBeVisible();
  await expect(page.getByText("tests/score.test.ts · normalizeScore")).toBeVisible();

  await page.getByText("tests/score.test.ts · normalizeScore").click();
  await expect(page.getByText(/normalizeScore\(25, 100\)/)).toBeVisible();

  await page.getByText("View captured output").click();
  await expect(page.getByText(/Coverage report from/)).toBeVisible();

  expect(backendCalls).toEqual([]);
});

test("demo mode serves honest empty and error states", async ({ page }) => {
  await page.goto("/?status=failed");

  await expect(page.getByText("0 matching runs")).toBeVisible();
  await expect(page.getByRole("heading", { name: "No runs match those filters" })).toBeVisible();
  await expect(page.getByText("Try a different repository fragment")).toBeVisible();

  await page.goto("/runs/missing");
  await expect(page.getByRole("heading", { level: 1, name: "No such run." })).toBeVisible();
  await expect(page.getByRole("link", { name: "Back to run console" })).toBeVisible();
});
