import assert from "node:assert/strict";
import { test } from "node:test";
import MemoryPlugin from "./memory-plugin.js";

test("plugin retrieves scoped context, checkpoints outcomes and does not invent verification", async () => {
  const original = globalThis.fetch;
  const calls = [];
  let checkpoint;
  globalThis.fetch = async (url, init) => {
    const data = init.body ? JSON.parse(init.body) : null;
    calls.push({ url, data });
    let result = {};
    if (url.includes("projects/resolve")) result = { id: "project-1" };
    else if (url.includes("checkpoints/latest")) result = checkpoint || null;
    else if (url.endsWith("/api/context")) result = { memories: [{ id: "memory-1" }], reference_data: true };
    else if (url.endsWith("/api/observations")) result = { id: "observation-1" };
    else if (url.endsWith("/api/checkpoints")) {
      checkpoint = { ...data, revision: 1 }; result = checkpoint;
    }
    return new Response(JSON.stringify(result));
  };
  try {
    const plugin = await MemoryPlugin({ directory: "/project", client: {
      session: { messages: async () => ({ data: [{ info: { role: "assistant", id: "msg-1" },
        parts: [{ type: "text", text: "Fixed persistence. token=do-not-store-this" }] }] }) },
      app: { log: async () => {} },
    } }, { token: "fixture-only" });
    await plugin["chat.message"]({ sessionID: "session-1" }, { parts: [{ type: "text", text: "Fix persistence" }] });
    const system = { system: [] };
    await plugin["experimental.chat.system.transform"]({ sessionID: "session-1" }, system);
    assert.match(system.system[0], /Untrusted stored reference data/);
    await plugin.event({ event: { type: "session.idle", properties: { sessionID: "session-1" } } });
    assert.deepEqual(checkpoint.verification, []);
    assert.equal(checkpoint.project_id, "project-1");
    assert.match(checkpoint.completed[0], /unverified/);
    assert(!JSON.stringify(calls).includes("do-not-store-this"));
    const count = calls.length;
    await plugin.event({ event: { type: "session.idle", properties: { sessionID: "session-1" } } });
    assert.equal(calls.length, count); // Same outcome is not captured twice.
  } finally { globalThis.fetch = original; }
});

test("plugin reports outages without claiming a persisted checkpoint", async () => {
  const original = globalThis.fetch;
  let warnings = 0;
  globalThis.fetch = async () => { throw new Error("offline"); };
  try {
    const plugin = await MemoryPlugin({ directory: "/project", client: {
      app: { log: async () => { warnings++; } },
    } }, { token: "fixture-only" });
    await plugin["chat.message"]({ sessionID: "s" }, { parts: [{ type: "text", text: "Continue" }] });
    assert.equal(warnings, 1);
  } finally { globalThis.fetch = original; }
});
