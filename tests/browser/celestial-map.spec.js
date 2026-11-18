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
    await expect(page.locator("#map-summary")).toContainText("stars");
    await expect(page.locator("#map-summary")).toContainText("linked paths");
    await expect(page.locator("#map-legend")).toContainText(label);
    await page.getByRole("button", { name: "Color: project", exact: true }).click();
    await expect(page.getByRole("button", { name: "Color: type", exact: true })).toBeVisible();
    await expect(page.locator("#map-legend")).toContainText("decision");
    const painted = await page.locator("#map-canvas").evaluate((element) => {
      const data = element.getContext("2d").getImageData(0, 0, element.width, element.height).data;
      return data.some((value, index) => index % 4 !== 3 && value > 24);
    });
    expect(painted).toBe(true);
    await page.locator(".map-index summary").click();
    await page.locator("#map-index .map-index-row").filter({ hasText: `${label} rollback` }).click();
    await expect(dialog).not.toBeVisible();
    await expect(page.locator("#detail-title")).toHaveText(`${label} rollback`);
    await page.locator("#detail-dialog").getByRole("button", { name: "Close", exact: true }).click();
    expect(errors).toEqual([]);
  } finally {
    for (const memory of [first, second]) {
      await page.request.delete(`/api/memories/${memory.id}`, { headers });
    }
    await page.request.delete(`/api/projects/${project.id}`, { headers });
  }
});
