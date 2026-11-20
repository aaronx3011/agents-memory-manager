import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const env = Object.fromEntries(readFileSync(process.env.MEMORY_ENV_FILE || new URL("../../.env", import.meta.url), "utf8")
  .trim().split("\n").map((line) => { const i = line.indexOf("="); return [line.slice(0, i), line.slice(i + 1)]; }));
const token = process.env.MEMORY_ADMIN_TOKEN || env.MEMORY_ADMIN_TOKEN;
const headers = { Authorization: `Bearer ${token}` };

test("owner can chart memories as a celestial relationship map", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const label = `Celestial map ${Date.now()}`;
  const project = await (await page.request.post("/api/projects", { headers, data: {
    name: label, repo_url: "https://example.test/celestial-map.git",
    aliases: ["/browser/celestial-map"],
  } })).json();
  const first = await (await page.request.post("/api/memories", { headers, data: {
    project_id: project.id, type: "decision", title: `${label} rollback`,
    content: "Rollback restores the previous replica after checksum verification.",
    sources: [{ kind: "test", reference: "Celestial map browser fixture" }],
    status: "active", idempotency_key: `${label}-first`,
  } })).json();
  const second = await (await page.request.post("/api/memories", { headers, data: {
    project_id: project.id, type: "procedural", title: `${label} promotion`,
    content: "Promote the replica after checksum verification completes.",
    sources: [{ kind: "test", reference: "Celestial map browser fixture" }],
    status: "active", idempotency_key: `${label}-second`,
  } })).json();
  try {
    const linked = await page.request.post(`/api/memories/${first.id}/links`, {
      headers, data: { target_id: second.id, kind: "relates_to" },
    });
    expect(linked.ok()).toBeTruthy();

    await page.goto("/");
    await page.getByLabel("Owner or scoped access token").fill(token);
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.locator("#project-filter").selectOption({ label });
    await page.getByRole("button", { name: "Celestial map", exact: true }).click();
    const dialog = page.locator("#map-dialog");
    await expect(dialog).toBeVisible();
    await expect(page.locator("#map-summary")).toContainText("2 stars");
    await expect(page.locator("#map-summary")).toContainText("1 linked paths");
    await expect(page.locator("#map-state")).toBeHidden();
    await expect(page.locator("#map-legend")).toContainText(label);
    await page.getByRole("button", { name: "Color: project", exact: true }).click();
    await expect(page.getByRole("button", { name: "Color: type", exact: true })).toBeVisible();
    await expect(page.locator("#map-legend")).toContainText("decision");
    const painted = await page.locator("#map-canvas").evaluate((element) => {
      const data = element.getContext("2d").getImageData(0, 0, element.width, element.height).data;
      return element.width > 300 && data.some((value, index) => index % 4 !== 3 && value > 24);
    });
    expect(painted).toBe(true);

    // Search narrows the list; Enter selects the first match and shows its relations.
    const rows = page.locator("#map-index .map-index-row");
    await expect(rows).toHaveCount(2);
    await page.getByLabel("Find a memory").fill("rollback");
    await expect(rows).toHaveCount(1);
    await expect(page.locator("#map-count")).toHaveText("1 of 2");
    await page.getByLabel("Find a memory").press("Enter");
    const selection = page.locator("#map-selection");
    await expect(selection.locator("h3")).toHaveText(`${label} rollback`);
    await expect(rows.first()).toHaveAttribute("aria-current", "true");
    await selection.getByRole("button", { name: new RegExp(`Related\\s*${label} promotion`) }).click();
    await expect(selection.locator("h3")).toHaveText(`${label} promotion`);

    // Hiding a group removes its stars from the list; Show all restores them.
    await page.getByLabel("Find a memory").fill("");
    await page.locator("#map-legend .map-chip", { hasText: "procedural" }).click();
    await expect(rows).toHaveCount(1);
    await expect(selection).toContainText("Select a star");
    await page.getByRole("button", { name: "Show all", exact: true }).click();
    await expect(rows).toHaveCount(2);

    // Keyboard: list rows are focusable buttons with arrow-key navigation.
    await rows.first().focus();
    await page.keyboard.press("ArrowDown");
    await expect(rows.nth(1)).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(rows.nth(1)).toHaveAttribute("aria-current", "true");

    // Opening a memory stacks the detail over the map, which stays open.
    await page.locator("#map-index .map-index-row", { hasText: `${label} rollback` }).click();
    await selection.getByRole("button", { name: "Open memory", exact: true }).click();
    await expect(page.locator("#detail-title")).toHaveText(`${label} rollback`);
    await page.locator("#detail-dialog").getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).not.toBeVisible();

    // Small screens: the map fills the viewport without horizontal overflow.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Celestial map", exact: true }).click();
    await expect(page.locator("#map-summary")).toContainText("2 stars");
    const layout = await page.evaluate(() => {
      const box = document.querySelector("#map-canvas").getBoundingClientRect();
      const dialog = document.querySelector("#map-dialog");
      return { width: box.width, height: box.height, overflow: dialog.scrollWidth - dialog.clientWidth };
    });
    expect(layout.width).toBeGreaterThan(300);
    expect(layout.height).toBeGreaterThan(300);
    expect(layout.overflow).toBeLessThanOrEqual(0);
    expect(errors).toEqual([]);
  } finally {
    for (const memory of [first, second]) {
      await page.request.delete(`/api/memories/${memory.id}`, { headers });
    }
    await page.request.delete(`/api/projects/${project.id}`, { headers });
  }
});
