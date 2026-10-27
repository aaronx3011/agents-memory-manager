from uuid import uuid4

from conftest import record

from agent_memory.store import Principal
from agent_memory.models import ProjectInput


def test_project_edit_resolve_and_remove_grants(client, project):
    project_id = project["id"]
    key = client.post("/api/credentials", json={
        "name": "scoped", "project_ids": [project_id],
    }).json()
    updated = client.put(f"/api/projects/{project_id}", json={
        "name": " renamed ", "repo_url": "https://example.test/new.git",
        "aliases": [" /new/path ", "/new/path", "/second/path"],
    })
    assert updated.status_code == 200
    assert updated.json()["id"] == project_id
    assert updated.json()["name"] == "renamed"
    assert updated.json()["aliases"] == ["/new/path", "/second/path"]
    for identity in ("renamed", "/new/path", "/second/path", "https://example.test/new.git"):
        assert client.get("/api/projects/resolve", params={"identity": identity}).json()["id"] == project_id
    assert client.get("/api/projects/resolve", params={"identity": "/test/project"}).status_code == 404
    assert client.delete(f"/api/projects/{project_id}").status_code == 200
    assert client.get("/api/credentials").json()[0]["project_ids"] == []
    assert client.delete(f"/api/projects/{project_id}").status_code == 404
    assert client.get("/api/projects", headers={"Authorization": f"Bearer {key['token']}"}).json() == []


def test_project_management_owner_only_and_isolated(client, project):
    key = client.post("/api/credentials", json={
        "name": "writer", "all_projects": True, "can_write": True,
    }).json()
    headers = {"Authorization": f"Bearer {key['token']}"}
    assert client.get("/api/session", headers=headers).json() == {"can_manage": False}
    assert client.get("/api/session").json() == {"can_manage": True}
    path = f"/api/projects/{project['id']}"
    assert client.post("/api/projects", json={"name": "denied"}, headers=headers).status_code == 403
    assert client.put(path, json={"name": "denied"}, headers=headers).status_code == 403
    assert client.delete(path, headers=headers).status_code == 403
    store = client.app.state.store
    other_owner = Principal(uuid4(), "other", admin=True)
    other = store.create_project(other_owner, ProjectInput(name="other-owner"))
    try:
        assert client.put(f"/api/projects/{other['id']}", json={"name": "denied"}).status_code == 404
        assert client.delete(f"/api/projects/{other['id']}").status_code == 404
    finally:
        with store.db.transaction(other_owner.owner_id) as conn:
            conn.execute("DELETE FROM audit_events")
            conn.execute("DELETE FROM projects")


def test_project_conflicts_and_validation(client, project):
    other = client.post("/api/projects", json={"name": "another"}).json()
    path = f"/api/projects/{project['id']}"
    assert client.put(path, json={"name": other["name"]}).status_code == 409
    assert client.put(path, json={"name": "   "}).status_code == 422
    assert client.put(path, json={"name": "valid", "aliases": [" "]}).status_code == 422
    assert client.put(f"/api/projects/{uuid4()}", json={"name": "missing"}).status_code == 404
    assert client.post("/api/memories", json=record(project["id"])).status_code == 201
    assert client.put(path, json={"name": "keeps-memory"}).status_code == 200
    assert client.get("/api/memories", params={"project_id": project["id"]}).json()[0]["project_id"] == project["id"]
    assert client.delete(path).status_code == 409
    assert len(client.get("/api/projects").json()) == 2


def test_project_with_checkpoint_or_job_cannot_be_removed(client, project):
    store = client.app.state.store
    owner = store.settings.owner_id
    with store.db.transaction(owner) as conn:
        conn.execute(
            "INSERT INTO jobs(id,owner_id,project_id,kind) VALUES (%s,%s,%s,'extraction')",
            (uuid4(), owner, project["id"]),
        )
    assert client.delete(f"/api/projects/{project['id']}").status_code == 409
    with store.db.transaction(owner) as conn:
        conn.execute("DELETE FROM jobs")
    response = client.post("/api/checkpoints", json={
        "project_id": project["id"], "session_id": "project-delete", "objective": "test",
        "next_action": "retain checkpoint",
    })
    assert response.status_code == 200
    assert client.delete(f"/api/projects/{project['id']}").status_code == 409
