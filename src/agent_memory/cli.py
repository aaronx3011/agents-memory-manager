import argparse
import json

from .config import Settings
from .db import Database
from .embeddings import Embedder
from .models import CaptureInput, ProjectInput
from .store import Store
from .worker import Worker


def enqueue_missing_passages(conn, embedding_model):
    """Enqueue one durable embedding job for each memory lacking passages for
    this model. Jobs get independent IDs; a single shared UUID would violate the
    jobs primary key on the first multi-row backfill."""
    return conn.execute(
        "INSERT INTO jobs(id,owner_id,project_id,memory_id,kind) "
        "SELECT gen_random_uuid(),owner_id,project_id,id,'embedding' FROM memories m "
        "WHERE m.status IN ('active','candidate') "
        "AND NOT EXISTS (SELECT 1 FROM memory_passages mp "
        "WHERE mp.memory_id=m.id AND mp.embedding_model=%s) "
        "RETURNING id",
        (embedding_model,),
    ).fetchall()


def main():
    parser = argparse.ArgumentParser(description="Local agent-memory administration")
    parser.add_argument("command", choices=["bootstrap", "status", "warmup", "token", "reindex"])
    parser.add_argument("--directory", help="Explicit client directory alias for bootstrap")
    parser.add_argument("--repository", help="Repository URL for bootstrap")
    parser.add_argument("--limit", type=int, default=500, help="Maximum jobs processed for reindex")
    args = parser.parse_args()
    settings = Settings.from_env()
    if args.command == "token":
        # Explicit local owner action only. Never used in service logs or URLs.
        print(settings.admin_token)
        return
    db = Database(settings.database_url)
    db.open()
    store = Store(db, settings)
    p = store.authenticate(settings.admin_token)
    try:
        if args.command == "bootstrap":
            projects = store.projects(p)
            project = next((x for x in projects if x["name"] == "agent-memory"), None)
            if project is None:
                project = store.create_project(p, ProjectInput(
                    name="agent-memory", repo_url=args.repository,
                    aliases=[args.directory] if args.directory else [],
                ))
            elif args.directory or args.repository:
                from uuid import UUID
                project = store.add_project_identity(p, UUID(project["id"]), args.directory, args.repository)
            memory = store.capture(p, CaptureInput(
                project_id=project["id"], type="decision",
                title="Central persistent memory across projects",
                content=("The owner requested a persistent database-backed memory system shared "
                         "across projects, stored outside project repositories. The local MVP uses "
                         "Docker PostgreSQL/pgvector, semantic and keyword recall, MCP tools, "
                         "and resumable session checkpoints."),
                sources=[{"kind": "user", "reference": "Task #105 owner clarification, 2026-10-26"}],
                evidence="reported", idempotency_key="bootstrap-central-memory-v1",
            ))
            print(json.dumps({"project_id": project["id"], "memory_id": memory["id"]}))
        elif args.command == "warmup":
            embedder = Embedder(settings)
            embedder.embed("Persistent project memory")
            worker = Worker(store, embedder)
            processed = 0
            while processed < 500 and worker.process_one():
                processed += 1
            print(json.dumps({"model_ready": embedder.ready, "jobs_processed": processed}))
        elif args.command == "reindex":
            # One-time/idempotent backfill: memories lacking passages for the
            # current embedding model get a fresh durable embedding job. Content
            # is not rewritten; only derived passage rows are (re)built.
            embedder = Embedder(settings)
            with db.transaction(p.owner_id) as conn:
                rows = enqueue_missing_passages(conn, embedder.model_name)
            stats = {"enqueued": len(rows), "processed": 0}
            embedder.embed("Persistent project memory")
            worker = Worker(store, embedder)
            while stats["processed"] < max(1, args.limit) and worker.process_one():
                stats["processed"] += 1
            print(json.dumps(stats, default=str))
        else:
            with db.transaction(p.owner_id) as conn:
                print(json.dumps({
                    "projects": len(store.projects(p)),
                    "memories": conn.execute("SELECT count(*) AS n FROM memories").fetchone()["n"],
                    "embedded": conn.execute(
                        "SELECT count(*) AS n FROM memories WHERE embedding IS NOT NULL",
                    ).fetchone()["n"],
                    "jobs": store.jobs(p),
                }, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
