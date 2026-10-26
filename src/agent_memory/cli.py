import argparse
import json

from .config import Settings
from .db import Database
from .embeddings import Embedder
from .models import CaptureInput, ProjectInput
from .store import Store
from .worker import Worker


def main():
    parser = argparse.ArgumentParser(description="Local agent-memory administration")
    parser.add_argument("command", choices=["bootstrap", "status", "warmup", "token"])
    parser.add_argument("--directory", help="Explicit client directory alias for bootstrap")
    parser.add_argument("--repository", help="Repository URL for bootstrap")
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
