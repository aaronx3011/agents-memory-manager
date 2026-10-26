from conftest import record


def rpc(client, method, params=None):
    response = client.post("/mcp/", headers={"Accept": "application/json, text/event-stream"}, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params or {},
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert "error" not in result, result
    return result["result"]


def test_mcp_tools_real_transport_and_session_recovery(client, project):
    initialized = rpc(client, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "integration-client", "version": "1"},
    })
    assert initialized["serverInfo"]["name"] == "agent-memory"
    names = [t["name"] for t in rpc(client, "tools/list")["tools"]]
    assert {"memory_capture", "memory_get_context", "memory_checkpoint", "memory_forget"} <= set(names)
    captured = rpc(client, "tools/call", {
        "name": "memory_capture", "arguments": {"data": record(project["id"])},
    })
    assert not captured.get("isError"), captured
    memory = captured["structuredContent"]
    saved = rpc(client, "tools/call", {"name": "memory_checkpoint", "arguments": {"data": {
        "project_id": project["id"], "session_id": "client-a", "objective": "Database continuity",
        "completed": ["Persisted memory"], "verification": ["MCP receipt received"],
        "next_action": "Resume in client B", "memory_ids": [memory["id"]],
    }}})
    assert not saved.get("isError"), saved
    resumed = rpc(client, "tools/call", {"name": "memory_get_context", "arguments": {"data": {
        "project_id": project["id"], "query": "database durability",
    }}})
    assert not resumed.get("isError"), resumed
    assert resumed["structuredContent"]["checkpoint"]["next_action"] == "Resume in client B"
    assert resumed["structuredContent"]["memories"][0]["id"] == memory["id"]


def test_mcp_rejects_missing_credentials(client):
    client.headers.pop("Authorization")
    response = client.post("/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response.status_code == 401
