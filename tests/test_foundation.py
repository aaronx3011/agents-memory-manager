from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from psycopg.errors import InsufficientPrivilege

from agent_memory.models import CorrectionInput
from agent_memory.store import Principal

from conftest import record


def test_project_registry_auth_and_scope(client, project):
    assert client.get("/api/projects/resolve", params={"identity": "/test/project"}).json() == project
    second = client.post("/api/projects", json={"name": "other"}).json()
    a = client.post("/api/memories", json=record(project["id"]))
    b = client.post("/api/memories", json=record(second["id"]))
    assert a.status_code == b.status_code == 201
    credential = client.post("/api/credentials", json={
        "name": "limited", "project_ids": [project["id"]],
    }).json()
    limited = {"Authorization": f"Bearer {credential['token']}"}
    assert len(client.get("/api/projects", headers=limited).json()) == 1
    assert client.get(f"/api/memories/{b.json()['id']}", headers=limited).status_code == 404
    assert client.get(f"/api/memories/{a.json()['id']}", headers=limited).status_code == 200
    assert client.post("/api/memories", json=record(project["id"]), headers=limited).status_code == 403
    assert client.get("/api/jobs", headers=limited).status_code == 403
    assert client.get("/api/jobs/" + b.json()["job"]["id"], headers=limited).status_code == 404
    assert client.get("/api/projects", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.delete("/api/credentials/" + credential["id"]).status_code == 200
    assert client.get("/api/projects", headers=limited).status_code == 401


def test_idempotency_and_correction_history(client, project):
    data = record(project["id"])
    first = client.post("/api/memories", json=data).json()
    second = client.post("/api/memories", json=data).json()
    assert first["id"] == second["id"] and second["duplicate"]
    data["content"] = "Different payload"
    assert client.post("/api/memories", json=data).status_code == 409
    replacement = record(project["id"], content="Backups are separate from Docker volumes.")
    replacement.pop("idempotency_key")
    correction = {"expected_revision": 1, "replacement": replacement}
    response = client.post(f"/api/memories/{first['id']}/correct", json=correction)
    assert response.status_code == 201, response.text
    new = response.json()
    assert new["supersedes"] == first["id"]
    old = client.get(f"/api/memories/{first['id']}").json()
    assert old["status"] == "superseded" and old["revision"] == 2
    assert old["history"][0]["snapshot"]["content"] == first["content"]
    assert old["replaced_by"] == [new["id"]]
    assert client.post(f"/api/memories/{first['id']}/correct", json=correction).status_code == 409


def test_transactional_concurrent_correction(client, project):
    memory = client.post("/api/memories", json=record(project["id"])).json()
    data = record(project["id"], content="Replacement")
    data.pop("idempotency_key")
    correction = CorrectionInput(expected_revision=1, replacement=data)
    store = client.app.state.store
    principal = store.authenticate(store.settings.admin_token)

    def correct(_):
        try:
            store.correct(principal, UUID(memory["id"]), correction)
            return 201
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(correct, range(2))) == [201, 409]


def test_database_role_and_owner_rls(client, project):
    db = client.app.state.db
    owner = client.app.state.store.settings.owner_id
    with db.transaction(owner) as conn:
        role = conn.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user",
        ).fetchone()
        assert not role["rolsuper"] and not role["rolbypassrls"]
        assert conn.execute("SELECT count(*) AS n FROM projects").fetchone()["n"] == 1
    with db.transaction(uuid4()) as conn:
        assert conn.execute("SELECT * FROM projects").fetchall() == []
        with pytest.raises(InsufficientPrivilege):
            conn.execute(
                "INSERT INTO projects(id,owner_id,name) VALUES (%s,%s,'forged')",
                (uuid4(), owner),
            )
    with db.pool.connection() as conn:
        assert conn.execute("SELECT * FROM projects").fetchall() == []
    other = Principal(uuid4(), "other-owner", admin=True)
    assert client.app.state.store.projects(other) == []


def test_checkpoint_revision_and_deleted_content(client, project):
    memory = client.post("/api/memories", json=record(project["id"])).json()
    data = {
        "project_id": project["id"], "session_id": "session-a", "objective": "Build memory",
        "completed": ["Created database"], "verification": ["Integration checks passed"],
        "pending": ["Connect second client"], "next_action": "Configure client",
        "memory_ids": [memory["id"]],
    }
    checkpoint = client.post("/api/checkpoints", json=data)
    assert checkpoint.status_code == 200, checkpoint.text
    assert client.post("/api/checkpoints", json=data).status_code == 409
    data["expected_revision"] = 1
    assert client.post("/api/checkpoints", json=data).json()["revision"] == 2
    deleted = client.delete(f"/api/memories/{memory['id']}")
    assert deleted.status_code == 200, deleted.text
    assert client.get(f"/api/memories/{memory['id']}").status_code == 404
    assert client.get("/api/checkpoints/latest", params={"project_id": project["id"]}).json() is None
    assert client.get("/api/jobs/" + memory["job"]["id"]).status_code == 404
    with client.app.state.db.transaction(client.app.state.store.settings.owner_id) as conn:
        assert conn.execute("SELECT * FROM revisions").fetchall() == []
        assert conn.execute("SELECT * FROM captures").fetchone()["memory_id"] is None
        assert conn.execute("SELECT * FROM tombstones").fetchone()["memory_id"] == UUID(memory["id"])


def test_personal_agent_key_has_future_project_access_but_no_management(client, project):
    key = client.post("/api/credentials", json={
        "name": "personal-agent", "all_projects": True, "can_write": True, "allow_shared": True,
    }).json()
    headers = {"Authorization": "Bearer " + key["token"]}
    future = client.post("/api/projects", json={"name": "future-project"}).json()
    assert len(client.get("/api/projects", headers=headers).json()) == 2
    assert client.post("/api/memories", json=record(future["id"]), headers=headers).status_code == 201
    assert client.post("/api/memories", json=record(None), headers=headers).status_code == 201
    assert client.post("/api/credentials", json={"name": "unauthorized"}, headers=headers).status_code == 403
    assert client.get("/api/export", headers=headers).status_code == 403


def test_bootstrap_identity_updates_preserve_aliases_and_refuse_wrong_repository(client, project):
    store = client.app.state.store
    owner = store.authenticate(store.settings.admin_token)
    updated = store.add_project_identity(owner, UUID(project["id"]), "/second/client/path", project["repo_url"])
    assert updated["aliases"] == ["/test/project", "/second/client/path"]
    assert store.resolve_project(owner, "/second/client/path")["id"] == project["id"]
    with pytest.raises(HTTPException) as failure:
        store.add_project_identity(owner, UUID(project["id"]), repository="https://other.test/repo.git")
    assert failure.value.status_code == 409
