import json
from uuid import UUID

from agent_memory.cli import enqueue_missing_passages
from agent_memory.models import SearchInput

from conftest import record

TAIL_HINT = "ZANZIBAR-TEST-TAIL"
TAIL_PARAGRAPH = (
    "The recovery drill for this project is internally labeled ZANZIBAR-TEST-TAIL and "
    "requires the on-call operator to verify the replica checksum before promoting it."
)
TAIL_QUERY = "operator must verify the replica checksum before promoting it"
MAX_TOKENS_INCLUDING_SPECIAL_TOKENS = 254


def drain(client):
    for _ in range(200):
        if not client.app.state.worker.process_one():
            return
    raise AssertionError("Worker did not drain")


def long_document(paragraphs=24):
    body = " ".join(f"proc{n:04d} applies procedure step for deployment {n}."
                    for n in range(paragraphs))
    return "\n\n".join([
        "Intro paragraph stating general deployment guidance for the fixture project.",
        "Middle paragraph about safe rollout and checksum verification. " + body,
        TAIL_PARAGRAPH,
    ])


def long_memory(client, project):
    return client.post("/api/memories", json=record(
        project["id"], title="Deployment recovery procedure",
        content=long_document(),
    )).json()


def passages(client, memory_id):
    with client.app.state.db.transaction(
        client.app.state.store.settings.owner_id,
    ) as conn:
        return conn.execute(
            "SELECT ordinal,token_count,text,content_hash,embedding,embedding_model,revision "
            "FROM memory_passages WHERE memory_id=%s ORDER BY ordinal", (UUID(memory_id),),
        ).fetchall()


def test_long_memory_is_split_within_truncation_window(client, project):
    memory = long_memory(client, project)
    drain(client)
    rows = passages(client, memory["id"])
    assert len(rows) > 1, "long content was not split into passages"
    # Including special tokens, every passage stays under the measured
    # truncation window of the configured model.
    assert all(row["token_count"] <= MAX_TOKENS_INCLUDING_SPECIAL_TOKENS
               for row in rows), [row["token_count"] for row in rows]
    assert rows[0]["ordinal"] == 0 and rows[-1]["ordinal"] == len(rows) - 1
    # Derived passage hashes are unique and the canonical content is untouched.
    hashes = [row["content_hash"] for row in rows]
    assert len(set(hashes)) == len(hashes)
    assert all(row["embedding"] is not None for row in rows)
    canonical = client.get("/api/memories/" + memory["id"]).json()
    assert canonical["content"].startswith("Intro paragraph")
    assert TAIL_HINT in canonical["content"]


def test_tail_content_is_retrievable_not_lost(client, project):
    client.post("/api/memories", json=record(
        project["id"], title="Unrelated styling fact", content="Charts use blue borders.",
    ))
    memory = long_memory(client, project)
    drain(client)
    result = client.post("/api/search", json={
        "project_id": project["id"], "query": TAIL_QUERY,
    }).json()
    assert result["mode"] == "hybrid"
    ids = [row["id"] for row in result["results"]]
    assert memory["id"] in ids
    match = next((row for row in result["results"] if row["id"] == memory["id"]), None)
    assert match is not None
    assert match.get("match", {}).get("kind") == "passage", match
    passage = match["passage"]
    assert TAIL_HINT in passage["text"]
    assert passage["similarity"] > 0.20


def test_context_uses_matching_passage_excerpt(client, project):
    memory = long_memory(client, project)
    drain(client)
    bundle = client.post("/api/context", json={
        "project_id": project["id"], "query": TAIL_QUERY + " " + TAIL_HINT.split("-")[0],
        "max_chars": 6000,
    }).json()
    assert bundle["memories"], "context bundle was empty"
    own = next(item for item in bundle["memories"] if item["id"] == memory["id"])
    assert TAIL_HINT in own["excerpt"], own["excerpt"][:200]
    assert own["excerpt_source"]["kind"] == "passage"
    assert own["excerpt_source"]["ordinal"] >= 1
    serialized = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    assert len(serialized) <= bundle["max_chars"]


def test_short_memory_single_passage_and_stable_result_shape(client, project):
    memory = client.post("/api/memories", json=record(project["id"])).json()
    drain(client)
    rows = passages(client, memory["id"])
    assert len(rows) == 1 and rows[0]["ordinal"] == 0
    result = client.post("/api/search", json={
        "project_id": project["id"], "query": "PostgreSQL durability rollback",
    }).json()
    top = result["results"][0]
    assert top["id"] == memory["id"]
    for key in ("id", "project_id", "type", "title", "evidence", "sources", "stale", "score"):
        assert key in top, key


def test_passages_follow_memory_lifecycle(client, project):
    memory = long_memory(client, project)
    drain(client)
    # The replacement schema forbids idempotency_key.
    replacement = {key: value for key, value in record(
        project["id"], title="Deployment recovery procedure v2",
        content="Recovery simplified: verify checksum, then promote replica.",
    ).items() if key != "idempotency_key"}
    superseding = client.post(
        f"/api/memories/{memory['id']}/correct",
        json={"expected_revision": 1, "replacement": replacement},
    ).json()
    result = client.post("/api/search", json={
        "project_id": project["id"], "query": "verify checksum promote replica recovery",
    }).json()
    assert result["results"][0]["id"] == superseding["id"]
    # Ranked recall must not resurface the superseded record.
    assert memory["id"] not in [row["id"] for row in result["results"]]
    # Owner purge cascades passage rows with the memory.
    assert client.delete("/api/memories/" + memory["id"]).json()
    assert passages(client, memory["id"]) == []
    result = client.post("/api/search", json={
        "project_id": project["id"], "query": "verify checksum promote replica",
    }).json()
    assert result["results"][0]["id"] == superseding["id"]


def test_backfill_query_targets_only_memories_lacking_current_model_passages(client, project):
    embedding_model = client.app.state.retrieval.embedder.model_name
    legacy = long_memory(client, project)
    drain(client)
    with client.app.state.db.transaction(
        client.app.state.store.settings.owner_id,
    ) as conn:
        conn.execute("DELETE FROM memory_passages")
    result = client.app.state.retrieval.search(
        client.app.state.store.authenticate(
            client.app.state.store.settings.admin_token),
        SearchInput(query="deployment procedure", project_id=project["id"]),
    )
    # Passages are gone but memory-level embeddings keep the mode hybrid.
    assert result["mode"] == "hybrid"
    assert any(row["id"] == legacy["id"] and "passage" not in row
               for row in result["results"])
    with client.app.state.db.transaction(
        client.app.state.store.settings.owner_id,
    ) as conn:
        enqueued = conn.execute(
            "INSERT INTO jobs(id,owner_id,project_id,memory_id,kind) "
            "SELECT gen_random_uuid(),owner_id,project_id,id,'embedding' FROM memories m "
            "WHERE m.status IN ('active','candidate') "
            "AND NOT EXISTS (SELECT 1 FROM memory_passages mp "
            "WHERE mp.memory_id=m.id AND mp.embedding_model=%s) RETURNING id",
            (embedding_model,),
        ).fetchall()
    assert len(enqueued) == 1
    drain(client)
    assert len(passages(client, legacy["id"])) > 1
    with client.app.state.db.transaction(
        client.app.state.store.settings.owner_id,
    ) as conn:
        remaining = conn.execute(
            "SELECT count(*) AS n FROM memories m "
            "WHERE m.status IN ('active','candidate') "
            "AND NOT EXISTS (SELECT 1 FROM memory_passages mp "
            "WHERE mp.memory_id=m.id AND mp.embedding_model=%s)",
            (embedding_model,),
        ).fetchone()["n"]
    assert remaining == 0


def test_reindex_enqueues_independent_jobs_for_each_memory(client, project):
    first = long_memory(client, project)
    second = client.post("/api/memories", json=record(
        project["id"], title="Backup restoration procedure",
        content=long_document(paragraphs=12),
    )).json()
    drain(client)
    with client.app.state.db.transaction(
        client.app.state.store.settings.owner_id,
    ) as conn:
        conn.execute("DELETE FROM memory_passages")
        rows = enqueue_missing_passages(
            conn, client.app.state.retrieval.embedder.model_name,
        )
    job_ids = [str(row["id"]) for row in rows]
    assert len(job_ids) == 2
    assert len(set(job_ids)) == 2
    drain(client)
    assert len(passages(client, first["id"])) > 1
    assert len(passages(client, second["id"])) > 1


def test_passages_respect_project_scope_and_grants(client, project):
    other = client.post("/api/projects", json={"name": "hidden-rag"}).json()
    hidden = long_memory(client, other)
    visible = long_memory(client, project)
    drain(client)
    credential = client.post("/api/credentials", json={
        "name": "one-project", "project_ids": [project["id"]],
    }).json()
    principal = client.app.state.store.authenticate(credential["token"])
    found = client.app.state.retrieval.search(principal, SearchInput(
        query=TAIL_QUERY, cross_project=True,
    ))
    ids = [row["id"] for row in found["results"]]
    assert visible["id"] in ids and hidden["id"] not in ids
