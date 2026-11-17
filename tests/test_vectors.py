from conftest import record

from test_passages import drain, long_memory


def vectors(client, memory_id):
    return client.get(f"/api/memories/{memory_id}/vectors")


def test_vector_view_exposes_embedding_passages_neighbors_and_projection(client, project):
    neighbor = client.post("/api/memories", json=record(
        project["id"], title="Deployment checklist",
        content="Verify the replica checksum before promoting a replica.",
    )).json()
    memory = long_memory(client, project)
    drain(client)
    response = vectors(client, memory["id"])
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["memory"]["id"] == memory["id"]
    assert data["memory"]["project_id"] == project["id"]
    assert data["embedding"]["present"] is True
    assert data["embedding"]["model"] == client.app.state.retrieval.embedder.model_name
    assert data["embedding_model"] == data["embedding"]["model"]
    stats = data["embedding"]["stats"]
    assert stats["dimensions"] == 384
    assert len(stats["values"]) == 384
    assert all(isinstance(value, float) for value in stats["values"])
    assert stats["norm"] > 0 and stats["nonzero"] > 0
    assert len(data["passages"]) > 1
    assert [item["ordinal"] for item in data["passages"]] == list(
        range(len(data["passages"]))
    )
    for passage in data["passages"]:
        assert passage["model"] == data["embedding_model"]
        assert passage["stats"]["dimensions"] == 384
        assert len(passage["stats"]["values"]) == 384
        assert -1 <= passage["cosine_to_record"] <= 1
    assert neighbor["id"] in [item["id"] for item in data["neighbors"]]
    similarities = [item["similarity"] for item in data["neighbors"]]
    assert similarities == sorted(similarities, reverse=True)
    assert all(-1 <= similarity <= 1 for similarity in similarities)
    points = data["projection"]["points"]
    assert len(points) == 1 + len(data["passages"]) + len(data["neighbors"])
    assert [point["kind"] for point in points].count("record") == 1
    assert all(0 <= point["x"] <= 1 and 0 <= point["y"] <= 1 for point in points)
    assert len(data["projection"]["explained"]) == 2
    assert sum(data["projection"]["explained"]) <= 1.00001
    assert data["job"]["status"] == "done"


def test_vector_view_reports_pending_embedding_without_error(client, project):
    memory = client.post("/api/memories", json=record(
        project["id"], title="Pending vector",
        content="This memory has not been embedded yet.",
    )).json()
    data = vectors(client, memory["id"]).json()
    assert data["embedding"]["present"] is False
    assert data["embedding"]["stats"] is None
    assert data["passages"] == []
    assert data["neighbors"] == []
    assert data["projection"]["points"] == []
    assert data["job"]["status"] == "pending"


def test_vector_view_respects_project_scope_and_shared_grants(client, project):
    other = client.post("/api/projects", json={"name": "vector-hidden"}).json()
    hidden = long_memory(client, other)
    visible = long_memory(client, project)
    peer = client.post("/api/memories", json=record(
        project["id"], title="Scoped peer",
        content="Verify the replica checksum before promoting the peer replica.",
    )).json()
    shared = client.post("/api/memories", json=record(
        None, title="Shared vector", content="Owner-wide deployment guidance.",
    )).json()
    drain(client)
    credential = client.post("/api/credentials", json={
        "name": "vector-view", "project_ids": [project["id"]],
    }).json()
    client.headers["Authorization"] = f"Bearer {credential['token']}"
    assert vectors(client, hidden["id"]).status_code == 404
    data = vectors(client, visible["id"]).json()
    ids = [item["id"] for item in data["neighbors"]]
    assert peer["id"] in ids
    assert hidden["id"] not in ids and shared["id"] not in ids
    point_ids = [point.get("id") for point in data["projection"]["points"] if "id" in point]
    assert hidden["id"] not in point_ids and shared["id"] not in point_ids
