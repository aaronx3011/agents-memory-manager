from conftest import record


def test_relationship_scope_and_context_expansion(client, project):
    first = client.post("/api/memories", json=record(
        project["id"], title="ERR_DEPLOY_42", content="Deployment issue investigation.",
    )).json()
    related = client.post("/api/memories", json=record(
        project["id"], title="Resolution", content="Update the service configuration.",
    )).json()
    other = client.post("/api/projects", json={"name": "other-scope"}).json()
    hidden = client.post("/api/memories", json=record(other["id"])).json()
    assert client.post(f"/api/memories/{first['id']}/links", json={
        "target_id": hidden["id"], "kind": "relates_to",
    }).status_code == 422
    assert client.post(f"/api/memories/{first['id']}/links", json={
        "target_id": related["id"], "kind": "relates_to",
    }).status_code == 200
    inspected = client.get("/api/memories/" + first["id"]).json()
    assert inspected["links"][0]["target_id"] == related["id"]
    context = client.post("/api/context", json={
        "project_id": project["id"], "query": "ERR_DEPLOY_42",
    })
    assert context.status_code == 200, context.text
    assert {r["id"] for r in context.json()["memories"]} == {first["id"], related["id"]}
