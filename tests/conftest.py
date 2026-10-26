import os
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent_memory.app import create_app
from agent_memory.config import Settings


@pytest.fixture
def client():
    if not os.getenv("DATABASE_URL"):
        pytest.fail("Tests require real PostgreSQL. Run: docker compose run --rm app pytest")
    settings = replace(Settings.from_env(), owner_id=uuid4(), worker_enabled=False)
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {settings.admin_token}"
        yield client
        # Each test uses an isolated owner; never erase records in the local owner's store.
        with app.state.db.transaction(settings.owner_id) as conn:
            conn.execute("UPDATE memories SET supersedes=NULL")
            for table in ("memory_links", "revisions", "jobs", "captures", "checkpoints",
                          "memories", "credentials", "audit_events", "tombstones", "projects"):
                conn.execute(f"DELETE FROM {table}")


@pytest.fixture
def project(client):
    response = client.post("/api/projects", json={
        "name": "test-project", "repo_url": "https://example.test/project.git",
        "aliases": ["/test/project"],
    })
    assert response.status_code == 201, response.text
    return response.json()


def record(project_id, **overrides):
    return {
        "project_id": project_id, "type": "semantic", "title": "PostgreSQL durability",
        "content": "The database stores records in a persistent Docker volume.",
        "sources": [{"kind": "test", "reference": "integration fixture"}],
        "idempotency_key": str(uuid4()), **overrides,
    }
