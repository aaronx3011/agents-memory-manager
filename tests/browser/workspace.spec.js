import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const env = Object.fromEntries(readFileSync(process.env.MEMORY_ENV_FILE || new URL("../../.env", import.meta.url), "utf8")
  .trim().split("\n").map((line) => { const i = line.indexOf("="); return [line.slice(0, i), line.slice(i + 1)]; }));

test("owner can log in, capture, inspect, correct, search and forget memory", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByLabel("Owner or scoped access token").fill(process.env.MEMORY_ADMIN_TOKEN || env.MEMORY_ADMIN_TOKEN);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Memory workspace" })).toBeVisible();
  await page.getByRole("button", { name: "+ Capture memory" }).click();
  const form = page.locator("#memory-form");
  await form.getByLabel("Scope").selectOption({ label: "agent-memory" });
  await form.getByLabel("Title", { exact: true }).fill("Browser verification fixture");
  await form.getByLabel("Knowledge").fill("Browser-tested local memory workflow uses PostgreSQL persistence.");
  await form.getByLabel("Source reference").fill("Playwright fixture; delete after verification");
  await form.getByRole("button", { name: "Save memory" }).click();
  await expect(page.locator("#memory-dialog")).not.toBeVisible();
  await page.locator(".record").filter({ hasText: "Browser verification fixture" }).click();
  await expect(page.locator("#detail-title")).toHaveText("Browser verification fixture");
  await expect(page.locator("#detail-body")).toContainText("Playwright fixture");
  await page.getByRole("button", { name: "Correct / replace" }).click();
  await form.getByLabel("Title", { exact: true }).fill("Corrected browser fixture");
  await form.getByRole("button", { name: "Save memory" }).click();
  await expect(page.locator("#memory-dialog")).not.toBeVisible();
  await page.locator("#query").fill("Corrected browser fixture");
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.locator("#retrieval-mode")).toContainText("hybrid");
  await page.locator(".record").filter({ hasText: "Corrected browser fixture" }).click();
  await expect(page.locator("#detail-body")).toContainText("supersedes");
  page.on("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Forget memory" }).click();
  await expect(page.locator("#detail-dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  await page.locator(".record").filter({ hasText: "Browser verification fixture" }).click();
  await page.getByRole("button", { name: "Forget memory" }).click();
  await expect(page.locator("#detail-dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Background jobs" }).click();
  await expect(page.getByRole("heading", { name: "Background processing" })).toBeVisible();
  await page.locator("#jobs-dialog").getByRole("button", { name: "Close" }).click();
  expect(errors).toEqual([]);
});
