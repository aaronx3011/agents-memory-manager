from conftest import record

from test_passages import drain


def edge_pairs(data):
    return {tuple(sorted((edge["source"], edge["target"]))) for edge in data["edges"]}


def test_map_combines_explicit_links_and_semantic_threads(client, project):
    first = client.post("/api/memories", json=record(
        project["id"], title="Deployment rollback",
        content="Rollback restores the previous replica after checksum verification.",
    )).json()
    second = client.post("/api/memories", json=record(
        project["id"], title="Replica promotion",
        content="Promote the replica after checksum verification completes.",
    )).json()
    third = client.post("/api/memories", json=record(
        project["id"], title="Colour palette",
        content="The dashboard uses muted teal accents.",
    )).json()
    linked = client.post(f"/api/memories/{first['id']}/links", json={
        "target_id": third["id"], "kind": "contradicts",
    })
    assert linked.status_code == 200, linked.text
    drain(client)
    response = client.get("/api/map", params={
        "project_id": project["id"], "neighbors": 1, "min_similarity": -1,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    nodes = {item["id"]: item for item in data["nodes"]}
    assert set(nodes) == {first["id"], second["id"], third["id"]}
    assert all(item["degree"] >= 1 for item in data["nodes"])
    assert all({"id", "title", "type", "status", "project_id", "stale", "degree"}
               <= set(item) for item in data["nodes"])
    pair = tuple(sorted((first["id"], third["id"])))
    assert pair in edge_pairs(data)
    assert any(edge["kind"] == "contradicts" and edge["source"] == first["id"]
               and edge["target"] == third["id"] for edge in data["edges"])
    semantic = [edge for edge in data["edges"] if edge["kind"] == "similarity"]
    assert semantic
    assert all(-1 <= edge["similarity"] <= 1 for edge in semantic)
    assert data["truncated"] is False


def test_map_respects_project_scope_and_shared_grants(client, project):
    other = client.post("/api/projects", json={"name": "map-hidden"}).json()
    hidden = client.post("/api/memories", json=record(
        other["id"], title="Hidden map memory", content="Never expose this project.",
    )).json()
    visible = client.post("/api/memories", json=record(
        project["id"], title="Visible map memory", content="Visible project memory.",
    )).json()
    shared = client.post("/api/memories", json=record(
        None, title="Shared map memory", content="Owner-wide shared memory.",
    )).json()
    credential = client.post("/api/credentials", json={
        "name": "map-scope", "project_ids": [project["id"]],
    }).json()
    shared_credential = client.post("/api/credentials", json={
        "name": "map-shared", "project_ids": [project["id"]], "allow_shared": True,
    }).json()
    client.headers["Authorization"] = f"Bearer {credential['token']}"
    data = client.get("/api/map").json()
    ids = {item["id"] for item in data["nodes"]}
    assert visible["id"] in ids
    assert hidden["id"] not in ids and shared["id"] not in ids
    assert {edge["source"] for edge in data["edges"]} <= ids
    assert {edge["target"] for edge in data["edges"]} <= ids

    client.headers["Authorization"] = f"Bearer {shared_credential['token']}"
    shared_data = client.get("/api/map").json()
    shared_ids = {item["id"] for item in shared_data["nodes"]}
    assert visible["id"] in shared_ids and shared["id"] in shared_ids
    assert hidden["id"] not in shared_ids


def test_map_bounds_nodes_without_embeddings_and_reports_truncation(client, project):
    memories = [client.post("/api/memories", json=record(
        project["id"], title=f"Unembedded map memory {index}",
        content=f"Pending semantic thread {index}.",
    )).json() for index in range(3)]
    data = client.get("/api/map", params={"project_id": project["id"], "limit": 2}).json()
    ids = {item["id"] for item in data["nodes"]}
    assert len(ids) == 2
    assert data["truncated"] is True
    assert all(item["degree"] == 0 for item in data["nodes"])
    assert data["edges"] == []
    memory_ids = {memory["id"] for memory in memories}
    assert all(item["id"] in memory_ids for item in data["nodes"])


def test_dashboard_serves_vendored_d3_before_ui(client):
    page = client.get("/").text
    assert page.index('src="/d3.min.js"') < page.index('src="/ui.js"')
    response = client.get("/d3.min.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.text.startswith("// https://d3js.org v7.9.0")
