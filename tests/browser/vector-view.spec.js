import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const env = Object.fromEntries(readFileSync(process.env.MEMORY_ENV_FILE || new URL("../../.env", import.meta.url), "utf8")
  .trim().split("\n").map((line) => { const i = line.indexOf("="); return [line.slice(0, i), line.slice(i + 1)]; }));
const token = process.env.MEMORY_ADMIN_TOKEN || env.MEMORY_ADMIN_TOKEN;
const headers = { Authorization: `Bearer ${token}` };

test("owner can inspect stored vectors, passages, neighbours and the embedding map", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const label = `Vector view ${Date.now()}`;
  const content = [
    "Deployment recovery guide. Verify the replica checksum before promoting it.",
    Array.from({ length: 60 }, (_, n) => `Step ${n}: confirm checklist item ${n} and record the result.`).join(" "),
    "Backup restoration uses the archive checksum and staging replica validation.",
  ].join("\n\n");
  const project = await (await page.request.post("/api/projects", { headers, data: {
    name: label, repo_url: "https://example.test/vector-view.git", aliases: ["/browser/vector-view"],
  } })).json();
  const first = await (await page.request.post("/api/memories", { headers, data: {
    project_id: project.id, type: "procedural", title: `${label} procedure`, content,
    sources: [{ kind: "document", reference: "Vector view browser fixture" }],
    evidence: "verified", verified_at: "2026-11-17T00:00:00Z", status: "active",
    tags: ["deployment"], idempotency_key: `${label}-first`,
  } })).json();
  const second = await (await page.request.post("/api/memories", { headers, data: {
    project_id: project.id, type: "semantic", title: `${label} neighbour`,
    content: "Promote a replica only after the checksum verification succeeds.",
    sources: [{ kind: "document", reference: "Vector view browser fixture" }],
    status: "active", idempotency_key: `${label}-second`,
  } })).json();
  try {
    let vectors;
    for (let attempt = 0; attempt < 120; attempt++) {
      vectors = await (await page.request.get(`/api/memories/${first.id}/vectors`, { headers })).json();
      if (vectors.embedding?.present && vectors.passages?.length > 1 && vectors.neighbors?.length) break;
      await page.waitForTimeout(500);
    }
    expect(vectors.embedding.present).toBe(true);
    expect(vectors.embedding.stats.dimensions).toBe(384);
    expect(vectors.passages.length).toBeGreaterThan(1);
    expect(vectors.neighbors.map((item) => item.id)).toContain(second.id);

    await page.goto("/");
    await page.getByLabel("Owner or scoped access token").fill(token);
    await page.getByRole("button", { name: "Connect", exact: true }).click();
    await page.locator("#query").fill(`${label} procedure`);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await page.locator(".record").filter({ hasText: `${label} procedure` }).first().click();
    await expect(page.locator("#detail-title")).toHaveText(`${label} procedure`);
    await page.getByRole("button", { name: "Vector view", exact: true }).click();
    const dialog = page.locator("#vector-dialog");
    await expect(dialog).toBeVisible();
    await expect(page.locator("#vector-summary")).toContainText("384 dimensions");
    await expect(page.locator("#vector-passages")).toContainText("Passage 1");
    await expect(page.locator("#vector-neighbors")).toContainText(`${label} neighbour`);
    await expect(page.locator("#vector-explained")).toContainText("PCA");
    await page.locator("#vector-passages .vector-row").nth(1).click();
    await expect(page.locator("#vector-axis")).toContainText("Passage 1");
    await expect(page.locator("#vector-stats")).toContainText("384 dimensions");
    for (const canvas of ["#vector-chart", "#vector-map"]) {
      const painted = await page.locator(canvas).evaluate((element) => {
        const data = element.getContext("2d").getImageData(0, 0, element.width, element.height).data;
        return data.some((value, index) => index % 4 !== 3 && value > 24);
      });
      expect(painted).toBe(true);
    }
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).not.toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    for (const memory of [first, second]) {
      await page.request.delete(`/api/memories/${memory.id}`, { headers });
    }
    await page.request.delete(`/api/projects/${project.id}`, { headers });
  }
});
