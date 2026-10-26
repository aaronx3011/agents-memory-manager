"""Exercise two independent MCP SDK sessions against the running local service."""

import asyncio
import os
from uuid import uuid4

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    base = os.getenv("MEMORY_URL", "http://app:8765")
    headers = {"Authorization": "Bearer " + os.environ["MEMORY_ADMIN_TOKEN"]}
    memory_id = None
    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        response = await http.get(base + "/api/projects/resolve", params={"identity": "agent-memory"})
        response.raise_for_status()
        project_id = response.json()["id"]
        try:
            async with streamable_http_client(base + "/mcp/", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as client_a:
                    await client_a.initialize()
                    tools = await client_a.list_tools()
                    captured = await client_a.call_tool("memory_capture", {"data": {
                        "project_id": project_id, "type": "episodic", "title": "MCP network smoke fixture",
                        "content": "Network client A stored a sourced outcome for client B to recall.",
                        "sources": [{"kind": "test", "reference": "scripts/mcp_smoke.py"}],
                        "idempotency_key": str(uuid4()),
                    }})
                    assert not captured.isError, captured
                    memory_id = captured.structuredContent["id"]
                    checkpoint = await client_a.call_tool("memory_checkpoint", {"data": {
                        "project_id": project_id, "session_id": "network-smoke-" + str(uuid4()),
                        "task_ref": "smoke:" + memory_id, "objective": "Verify persistent MCP session continuity",
                        "completed": ["Captured a sourced outcome over the network"],
                        "verification": ["Received committed capture receipt"],
                        "next_action": "Resume from an independent MCP client", "memory_ids": [memory_id],
                    }})
                    assert not checkpoint.isError, checkpoint
            # A completely new MCP session, not a continuation of the old context.
            async with streamable_http_client(base + "/mcp/", http_client=http) as (read, write, _):
                async with ClientSession(read, write) as client_b:
                    await client_b.initialize()
                    recovered = await client_b.call_tool("memory_get_context", {"data": {
                        "project_id": project_id, "query": "Network smoke sourced outcome",
                        "task_ref": "smoke:" + memory_id,
                    }})
                    assert not recovered.isError, recovered
                    context = recovered.structuredContent
                    assert context["checkpoint"]["next_action"] == "Resume from an independent MCP client"
                    assert memory_id in [r["id"] for r in context["memories"]]
                    print(f"MCP network smoke passed: {len(tools.tools)} tools, two clients, persisted checkpoint and cited recall")
        finally:
            if memory_id:
                response = await http.delete(base + "/api/memories/" + memory_id)
                response.raise_for_status()


if __name__ == "__main__":
    asyncio.run(main())
