from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .db import Database
from .embeddings import Embedder
from .mcp_server import create_mcp
from .models import (
    CaptureInput, CheckpointInput, ContextInput, CorrectionInput, CredentialInput,
    LinkInput, ObservationInput, ProjectInput, SearchInput, StatusInput,
)
from .retrieval import Retrieval
from .store import Store
from .worker import Worker, observe


def create_app(settings=None, embedder=None):
    settings = settings or Settings.from_env()
    db = Database(settings.database_url)
    store = Store(db, settings)
    embedder = embedder or Embedder(settings)
    retrieval = Retrieval(store, embedder)
    worker = Worker(store, embedder)
    mcp = create_mcp(store, retrieval)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(db.open)
        if settings.worker_enabled:
            worker.start()
        try:
            async with mcp.session_manager.run():
                yield
        finally:
            await run_in_threadpool(worker.close)
            await run_in_threadpool(db.close)

    app = FastAPI(title="Agent Memory", version="0.1.0", lifespan=lifespan)
    app.state.store, app.state.worker = store, worker
    app.state.retrieval, app.state.db = retrieval, db

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.url.path.startswith(("/api/", "/mcp")):
            header = request.headers.get("authorization", "")
            if not header.startswith("Bearer "):
                return JSONResponse({"detail": "Bearer credential required"}, 401)
            try:
                request.state.principal = await run_in_threadpool(
                    store.authenticate, header[7:],
                )
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, exc.status_code)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def principal(request: Request):
        return request.state.principal

    @app.exception_handler(psycopg.Error)
    async def database_failure(request, exc):
        code = 409 if isinstance(exc, psycopg.IntegrityError) else 503
        return JSONResponse({"detail": "Database operation failed", "category": type(exc).__name__}, code)

    @app.get("/health")
    def health():
        with db.pool.connection() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "ok", "embeddings_ready": embedder.ready,
                "embedding_error": embedder.last_error,
                "extraction_configured": bool(settings.extraction_base_url and settings.extraction_model)}

    @app.get("/api/projects")
    def projects(p=Depends(principal)):
        return store.projects(p)

    @app.post("/api/projects", status_code=201)
    def create_project(data: ProjectInput, p=Depends(principal)):
        return store.create_project(p, data)

    @app.get("/api/projects/resolve")
    def resolve_project(identity: str, p=Depends(principal)):
        return store.resolve_project(p, identity)

    @app.get("/api/session")
    def session(p=Depends(principal)):
        return {"can_manage": p.admin}

    @app.put("/api/projects/{project_id}")
    def update_project(project_id: UUID, data: ProjectInput, p=Depends(principal)):
        return store.update_project(p, project_id, data)

    @app.delete("/api/projects/{project_id}")
    def delete_project(project_id: UUID, p=Depends(principal)):
        return store.delete_project(p, project_id)

    @app.get("/api/credentials")
    def credentials(p=Depends(principal)):
        return store.credentials(p)

    @app.post("/api/credentials", status_code=201)
    def create_credential(data: CredentialInput, p=Depends(principal)):
        return store.create_credential(p, data)

    @app.delete("/api/credentials/{credential_id}")
    def revoke(credential_id: UUID, p=Depends(principal)):
        return store.revoke_credential(p, credential_id)

    @app.get("/api/memories")
    def memories(project_id: UUID | None = None, limit: int = Query(100, ge=1, le=200),
                 offset: int = Query(0, ge=0), p=Depends(principal)):
        return store.list_memories(p, project_id, limit, offset)

    @app.post("/api/memories", status_code=201)
    def capture(data: CaptureInput, p=Depends(principal)):
        return store.capture(p, data)

    @app.get("/api/memories/{memory_id}")
    def get(memory_id: UUID, p=Depends(principal)):
        return store.get(p, memory_id)

    @app.post("/api/memories/{memory_id}/correct", status_code=201)
    def correct(memory_id: UUID, data: CorrectionInput, p=Depends(principal)):
        return store.correct(p, memory_id, data)

    @app.post("/api/memories/{memory_id}/status")
    def status(memory_id: UUID, data: StatusInput, p=Depends(principal)):
        return store.status(p, memory_id, data)

    @app.delete("/api/memories/{memory_id}")
    def forget(memory_id: UUID, p=Depends(principal)):
        return store.forget(p, memory_id)

    @app.post("/api/memories/{memory_id}/links")
    def link(memory_id: UUID, data: LinkInput, p=Depends(principal)):
        return store.link(p, memory_id, data)

    @app.post("/api/search")
    def search(data: SearchInput, p=Depends(principal)):
        return retrieval.search(p, data)

    @app.post("/api/context")
    def context(data: ContextInput, p=Depends(principal)):
        return retrieval.context(p, data)

    @app.post("/api/checkpoints")
    def checkpoint(data: CheckpointInput, p=Depends(principal)):
        return store.checkpoint(p, data)

    @app.get("/api/checkpoints/latest")
    def latest_checkpoint(project_id: UUID, task_ref: str | None = None,
                          session_id: str | None = None, p=Depends(principal)):
        return store.latest_checkpoint(p, project_id, task_ref, session_id)

    @app.post("/api/observations", status_code=201)
    def observation(data: ObservationInput, p=Depends(principal)):
        return observe(store, p, data)

    @app.get("/api/jobs")
    def jobs(p=Depends(principal)):
        return store.jobs(p)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: UUID, p=Depends(principal)):
        return store.job(p, job_id)

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: UUID, p=Depends(principal)):
        return store.retry_job(p, job_id)

    @app.get("/api/export")
    def export(p=Depends(principal)):
        p.manage()
        with db.transaction(p.owner_id) as conn:
            from .store import public
            return {"schema_version": 1, "projects": store.projects(p),
                    "memories": [public(r) for r in conn.execute(
                        "SELECT * FROM memories ORDER BY created_at",
                    ).fetchall()],
                    "checkpoints": [public(r) for r in conn.execute(
                        "SELECT * FROM checkpoints ORDER BY updated_at",
                    ).fetchall()]}

    web = Path(__file__).parent / "web"

    @app.get("/", include_in_schema=False)
    def ui():
        return FileResponse(web / "index.html")

    @app.get("/ui.js", include_in_schema=False)
    def ui_js():
        return FileResponse(web / "ui.js", media_type="application/javascript")

    @app.get("/ui.css", include_in_schema=False)
    def ui_css():
        return FileResponse(web / "ui.css", media_type="text/css")

    app.mount("/mcp", mcp_app)
    return app
