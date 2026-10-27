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

test("owner can create, edit and remove projects from the management panel", async ({ page }) => {
  const name = `Admin browser ${Date.now()}`;
  await page.goto("/");
  await page.getByLabel("Owner or scoped access token").fill(process.env.MEMORY_ADMIN_TOKEN || env.MEMORY_ADMIN_TOKEN);
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await page.getByRole("button", { name: "Manage projects", exact: true }).click();
  const panel = page.locator("#projects-dialog"), form = page.locator("#project-form");
  await panel.getByRole("button", { name: "Register project" }).click();
  await form.getByLabel("Name", { exact: true }).fill(name);
  await form.getByLabel("Repository URL (optional)").fill("https://example.test/admin.git");
  await form.getByLabel("Directory aliases").fill("/browser/one\n/browser/two");
  await form.getByRole("button", { name: "Register", exact: true }).click();
  await expect(page.locator("#project-dialog")).not.toBeVisible();
  await panel.getByRole("button", { name: `Edit ${name}`, exact: true }).click();
  await expect(form.getByLabel("Directory aliases")).toHaveValue("/browser/one\n/browser/two");
  await form.getByLabel("Name", { exact: true }).fill(`${name} renamed`);
  await form.getByLabel("Directory aliases").fill("/browser/corrected");
  await form.getByRole("button", { name: "Save changes" }).click();
  await expect(page.locator("#project-dialog")).not.toBeVisible();
  await expect(panel).toContainText("/browser/corrected");
  page.once("dialog", (dialog) => dialog.dismiss());
  await panel.getByRole("button", { name: `Remove ${name} renamed`, exact: true }).click();
  await expect(panel.getByRole("button", { name: `Edit ${name} renamed`, exact: true })).toBeVisible();
  const headers = { Authorization: `Bearer ${process.env.MEMORY_ADMIN_TOKEN || env.MEMORY_ADMIN_TOKEN}` };
  const response = await page.request.get("/api/projects", { headers });
  const project = (await response.json()).find((project) => project.name === `${name} renamed`);
  const captured = await page.request.post("/api/memories", { headers, data: {
    project_id: project.id, type: "semantic", title: "Project removal protection",
    content: "Stored project data must not be silently removed.",
    sources: [{ kind: "test", reference: "Project admin browser test" }],
    idempotency_key: name,
  } });
  expect(captured.ok()).toBeTruthy();
  const memory = await captured.json();
  page.once("dialog", (dialog) => dialog.accept());
  await panel.getByRole("button", { name: `Remove ${name} renamed`, exact: true }).click();
  await expect(page.locator("#message")).toContainText("Project contains");
  await expect(panel.getByRole("button", { name: `Edit ${name} renamed`, exact: true })).toBeVisible();
  expect((await page.request.delete(`/api/memories/${memory.id}`, { headers })).ok()).toBeTruthy();
  page.once("dialog", (dialog) => dialog.accept());
  await panel.getByRole("button", { name: `Remove ${name} renamed`, exact: true }).click();
  await expect(panel.getByRole("button", { name: `Edit ${name} renamed`, exact: true })).toHaveCount(0);
  await panel.getByRole("button", { name: "Close", exact: true }).click();
  await expect(page.locator("#project-filter option").filter({ hasText: name })).toHaveCount(0);
});
