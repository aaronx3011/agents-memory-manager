from uuid import UUID

from dataclasses import replace

import httpx

from conftest import record


def test_failed_embedding_retry_is_durable_and_redacted(client, project, monkeypatch):
    memory = client.post("/api/memories", json=record(project["id"])).json()

    def fail(_):
        raise RuntimeError("secret credential in a provider exception")

    monkeypatch.setattr(client.app.state.worker.embedder, "embed", fail)
    assert client.app.state.worker.process_one()
    job = client.get("/api/jobs/" + memory["job"]["id"]).json()
    assert job["attempts"] == 1 and job["status"] == "pending"
    assert job["error"] == "RuntimeError" and "secret" not in str(job)
    with client.app.state.db.transaction(client.app.state.store.settings.owner_id) as conn:
        conn.execute(
            "UPDATE jobs SET attempts=5,status='running',leased_at=now()-interval '10 minutes'",
        )
    assert not client.app.state.worker.process_one()
    assert client.get("/api/jobs/" + memory["job"]["id"]).json()["status"] == "failed"
    assert client.post("/api/jobs/" + memory["job"]["id"] + "/retry").status_code == 200


def test_delete_during_embedding_cannot_resurrect_memory(client, project, monkeypatch):
    memory = client.post("/api/memories", json=record(project["id"])).json()

    def concurrent_delete(_):
        assert client.delete("/api/memories/" + memory["id"]).status_code == 200
        import numpy as np
        return np.ones(384, dtype=np.float32)

    monkeypatch.setattr(client.app.state.worker.embedder, "embed", concurrent_delete)
    assert client.app.state.worker.process_one()
    assert client.get("/api/memories/" + memory["id"]).status_code == 404
    assert client.get("/api/jobs/" + memory["job"]["id"]).status_code == 404


def test_embedding_completion_does_not_deadlock_with_database_delete(client, project, monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import numpy as np

    memory = client.post("/api/memories", json=record(project["id"])).json()
    started, finish = threading.Event(), threading.Event()

    def slow_embedding(_):
        started.set()
        assert finish.wait(5)
        return np.ones(384, dtype=np.float32)

    monkeypatch.setattr(client.app.state.worker.embedder, "embed", slow_embedding)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.app.state.worker.process_one)
        assert started.wait(5)
        with client.app.state.db.transaction(client.app.state.store.settings.owner_id) as conn:
            conn.execute("SELECT id FROM memories WHERE id=%s FOR UPDATE", (UUID(memory["id"]),))
            finish.set()
            time.sleep(0.1)  # Allow background completion to reach its database transaction.
            conn.execute("SET LOCAL lock_timeout='500ms'")
            conn.execute("DELETE FROM memories WHERE id=%s", (UUID(memory["id"]),))
        assert future.result(timeout=5)
    assert client.get("/api/memories/" + memory["id"]).status_code == 404


def test_deletion_purges_derived_content_and_observation_fallback(client, project):
    observation = client.post("/api/observations", json={
        "project_id": project["id"], "text": "We learned that PostgreSQL requires a durable volume.",
        "source": {"kind": "session", "reference": "session:fixture"},
        "idempotency_key": "observation-1",
    })
    assert observation.status_code == 201, observation.text
    source = observation.json()
    assert source["automatic_extraction"] is False
    derived = client.post("/api/memories", json=record(project["id"], status="candidate")).json()
    with client.app.state.db.transaction(client.app.state.store.settings.owner_id) as conn:
        conn.execute(
            "INSERT INTO memory_links VALUES (%s,%s,%s,'derived_from')",
            (client.app.state.store.settings.owner_id, UUID(derived["id"]), UUID(source["id"])),
        )
    removed = client.delete("/api/memories/" + source["id"]).json()
    assert removed["purged_records"] == 2
    assert client.get("/api/memories/" + derived["id"]).status_code == 404


def test_configured_extraction_preserves_scope_provenance_and_uncertainty(client, project, monkeypatch):
    store = client.app.state.store
    store.settings = replace(store.settings, extraction_base_url="https://provider.test/v1",
                             extraction_model="fixture-model")
    real_client = httpx.Client

    def provider(request):
        assert str(request.url) == "https://provider.test/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content":
            '{"memories": [{"type":"procedural","title":"Durable volumes",'
            '"content":"Use a persistent Docker volume for PostgreSQL."}]}'}}]})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(provider),
    ))
    response = client.post("/api/observations", json={
        "project_id": project["id"], "text": "Retain database data on a Docker volume.",
        "source": {"kind": "session", "reference": "session:extract"},
        "idempotency_key": "extract-once",
    })
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["automatic_extraction"]
    assert client.app.state.worker.process_one()  # Embed original observation.
    assert client.app.state.worker.process_one()  # Extract candidate.
    job = store.job(store.authenticate(store.settings.admin_token), UUID(receipt["extraction_job"]["id"]))
    assert job["status"] == "done", job
    memories = client.get("/api/memories").json()
    candidate = next(m for m in memories if m["type"] == "procedural")
    assert candidate["project_id"] == project["id"]
    assert candidate["status"] == "candidate" and candidate["evidence"] == "inferred"
    assert candidate["sources"][0]["reference"] == "session:extract"
    assert client.delete("/api/memories/" + receipt["id"]).json()["purged_records"] == 2
