import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from .models import MemoryInput


def fail(code, detail):
    raise HTTPException(code, detail)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def public(row):
    if row is None:
        return None
    result = {k: v for k, v in row.items() if k not in (
        "owner_id", "embedding", "search", "token_hash", "content_hash", "payload_hash",
    )}
    if "review_after" in row:
        result["stale"] = bool(
            row["review_after"] and row["review_after"] < datetime.now(timezone.utc)
        )
    return jsonable_encoder(result)


@dataclass(frozen=True)
class Principal:
    owner_id: UUID
    actor: str
    admin: bool = False
    project_ids: tuple[UUID, ...] = ()
    allow_shared: bool = False
    can_write: bool = False
    all_projects: bool = False

    def permit(self, project_id, write=False):
        if write and not (self.admin or self.can_write):
            fail(403, "Credential is read-only")
        if not self.admin:
            if project_id is None and not self.allow_shared:
                fail(403, "Shared memory access is not granted")
            if project_id is not None and not self.all_projects and project_id not in self.project_ids:
                fail(404, "Project or record not found")

    def manage(self):
        if not self.admin:
            fail(403, "Owner management credential required")


class Store:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def authenticate(self, token):
        if secrets.compare_digest(token, self.settings.admin_token):
            return Principal(self.settings.owner_id, "owner", True, (), True, True)
        try:
            prefix, owner, secret = token.split(".")
            owner = UUID(owner)
            if prefix != "am" or len(secret) < 32:
                raise ValueError()
        except (ValueError, AttributeError):
            fail(401, "Invalid credential")
        with self.db.transaction(owner) as conn:
            row = conn.execute(
                "SELECT * FROM credentials WHERE token_hash=%s AND NOT revoked",
                (hashlib.sha256(token.encode()).hexdigest(),),
            ).fetchone()
        if not row:
            fail(401, "Invalid credential")
        return Principal(owner, str(row["id"]), False, tuple(row["project_ids"]),
                         row["allow_shared"], row["can_write"], row["all_projects"])

    def _project(self, conn, p, project_id, write=False):
        p.permit(project_id, write)
        if project_id is not None and not conn.execute(
            "SELECT id FROM projects WHERE id=%s", (project_id,),
        ).fetchone():
            fail(404, "Project not found")

    def _record(self, conn, p, memory_id, lock=False):
        row = conn.execute(
            "SELECT * FROM memories WHERE id=%s" + (" FOR UPDATE" if lock else ""),
            (memory_id,),
        ).fetchone()
        if not row:
            fail(404, "Memory not found")
        p.permit(row["project_id"])
        return row

    @staticmethod
    def _audit(conn, p, action, target):
        conn.execute(
            "INSERT INTO audit_events(owner_id,actor,action,target_id) VALUES (%s,%s,%s,%s)",
            (p.owner_id, p.actor, action, target),
        )

    def projects(self, p):
        with self.db.transaction(p.owner_id) as conn:
            rows = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
        return [public(r) for r in rows if p.admin or p.all_projects or r["id"] in p.project_ids]

    def create_project(self, p, data):
        p.manage()
        with self.db.transaction(p.owner_id) as conn:
            try:
                row = conn.execute(
                    "INSERT INTO projects(id,owner_id,name,repo_url,aliases) "
                    "VALUES (%s,%s,%s,%s,%s) RETURNING *",
                    (uuid4(), p.owner_id, data.name, data.repo_url, Jsonb(data.aliases)),
                ).fetchone()
            except UniqueViolation:
                fail(409, "Project name already exists")
            self._audit(conn, p, "project.create", row["id"])
        return public(row)

    def update_project(self, p, project_id, data):
        p.manage()
        with self.db.transaction(p.owner_id) as conn:
            self._project(conn, p, project_id, write=True)
            try:
                row = conn.execute(
                    "UPDATE projects SET name=%s,repo_url=%s,aliases=%s WHERE id=%s RETURNING *",
                    (data.name, data.repo_url, Jsonb(data.aliases), project_id),
                ).fetchone()
            except UniqueViolation:
                fail(409, "Project name already exists")
            if not row:
                fail(404, "Project not found")
            self._audit(conn, p, "project.update", project_id)
        return public(row)

    def delete_project(self, p, project_id):
        p.manage()
        with self.db.transaction(p.owner_id) as conn:
            row = conn.execute("SELECT id FROM projects WHERE id=%s FOR UPDATE", (project_id,)).fetchone()
            if not row:
                fail(404, "Project not found")
            # The row lock serializes deletion with foreign-key writers.
            for table in ("memories", "checkpoints", "jobs"):
                if conn.execute(
                    f"SELECT 1 FROM {table} WHERE project_id=%s LIMIT 1", (project_id,),
                ).fetchone():
                    fail(409, "Project contains memories, checkpoints, or jobs. Remove its stored data before deleting it.")
            conn.execute(
                "UPDATE credentials SET project_ids=array_remove(project_ids,%s) WHERE %s=ANY(project_ids)",
                (project_id, project_id),
            )
            conn.execute("DELETE FROM projects WHERE id=%s", (project_id,))
            self._audit(conn, p, "project.delete", project_id)
        return {"deleted": True, "id": str(project_id)}

    def resolve_project(self, p, identity):
        matches = [r for r in self.projects(p) if identity in (
            r["id"], r["name"], r["repo_url"], *r["aliases"],
        )]
        if len(matches) != 1:
            fail(409 if matches else 404, "Ambiguous project" if matches else "Register project first")
        return matches[0]

    def add_project_identity(self, p, project_id, directory=None, repository=None):
        """Explicit bootstrap identity updates retain previously registered client aliases."""
        p.manage()
        with self.db.transaction(p.owner_id) as conn:
            self._project(conn, p, project_id, write=True)
            row = conn.execute("SELECT * FROM projects WHERE id=%s FOR UPDATE", (project_id,)).fetchone()
            aliases = list(dict.fromkeys([*row["aliases"], *([directory] if directory else [])]))
            if row["repo_url"] and repository and row["repo_url"] != repository:
                fail(409, "Existing project repository differs; resolve project identity explicitly")
            updated = conn.execute(
                "UPDATE projects SET aliases=%s,repo_url=%s WHERE id=%s RETURNING *",
                (Jsonb(aliases), repository or row["repo_url"], project_id),
            ).fetchone()
            self._audit(conn, p, "project.identity", project_id)
        return public(updated)

    def create_credential(self, p, data):
        p.manage()
        token = f"am.{p.owner_id}.{secrets.token_urlsafe(40)}"
        with self.db.transaction(p.owner_id) as conn:
            for project in data.project_ids:
                self._project(conn, p, project)
            row = conn.execute(
                "INSERT INTO credentials(id,owner_id,name,token_hash,project_ids,allow_shared,can_write,all_projects) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (uuid4(), p.owner_id, data.name, hashlib.sha256(token.encode()).hexdigest(),
                 data.project_ids, data.allow_shared, data.can_write, data.all_projects),
            ).fetchone()
            self._audit(conn, p, "credential.create", row["id"])
        return {**public(row), "token": token}

    def credentials(self, p):
        p.manage()
        with self.db.transaction(p.owner_id) as conn:
            return [public(r) for r in conn.execute(
                "SELECT * FROM credentials ORDER BY created_at DESC",
            ).fetchall()]

    def revoke_credential(self, p, credential_id):
        p.manage()
        with self.db.transaction(p.owner_id) as conn:
            row = conn.execute(
                "UPDATE credentials SET revoked=true WHERE id=%s RETURNING id", (credential_id,),
            ).fetchone()
            if not row:
                fail(404, "Credential not found")
            self._audit(conn, p, "credential.revoke", credential_id)
        return {"revoked": True}

    def _insert_memory(self, conn, p, data, supersedes=None):
        memory_id = uuid4()
        normalized = data.model_dump(mode="json")
        row = conn.execute(
            "INSERT INTO memories(id,owner_id,project_id,type,title,content,sources,evidence,status,"
            "created_by,verified_at,review_after,tags,content_hash,supersedes) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (memory_id, p.owner_id, data.project_id, data.type, data.title, data.content,
             Jsonb(normalized["sources"]), data.evidence, data.status, p.actor,
             data.verified_at, data.review_after, data.tags, digest(normalized), supersedes),
        ).fetchone()
        job = conn.execute(
            "INSERT INTO jobs(id,owner_id,project_id,memory_id,kind) "
            "VALUES (%s,%s,%s,%s,'embedding') RETURNING id,status",
            (uuid4(), p.owner_id, data.project_id, memory_id),
        ).fetchone()
        self._audit(conn, p, "memory.capture", memory_id)
        return {**public(row), "job": public(job)}

    def capture(self, p, data):
        normalized = data.model_dump(mode="json", exclude={"idempotency_key"})
        payload_hash = digest(normalized)
        with self.db.transaction(p.owner_id) as conn:
            self._project(conn, p, data.project_id, write=True)
            key = f"{p.owner_id}:{p.actor}:{data.idempotency_key}"
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
            existing = conn.execute(
                "SELECT * FROM captures WHERE actor=%s AND idempotency_key=%s",
                (p.actor, data.idempotency_key),
            ).fetchone()
            if existing:
                if existing["payload_hash"] != payload_hash:
                    fail(409, "Idempotency key was used for different content")
                if existing["memory_id"] is None:
                    fail(410, "Previously captured memory was deleted")
                row = self._record(conn, p, existing["memory_id"])
                return {**public(row), "duplicate": True}
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"content:{p.owner_id}:{data.project_id}:{payload_hash}",),
            )
            row = conn.execute(
                "SELECT * FROM memories WHERE project_id IS NOT DISTINCT FROM %s "
                "AND content_hash=%s AND status IN ('active','candidate') LIMIT 1",
                (data.project_id, payload_hash),
            ).fetchone()
            if row:
                result = {**public(row), "duplicate": True}
            else:
                result = self._insert_memory(conn, p, MemoryInput.model_validate(normalized))
            conn.execute(
                "INSERT INTO captures(id,owner_id,actor,idempotency_key,payload_hash,memory_id) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (uuid4(), p.owner_id, p.actor, data.idempotency_key, payload_hash, UUID(result["id"])),
            )
        return result

    def get(self, p, memory_id):
        with self.db.transaction(p.owner_id) as conn:
            row = self._record(conn, p, memory_id)
            history = conn.execute(
                "SELECT revision,snapshot,created_at FROM revisions WHERE memory_id=%s "
                "ORDER BY revision", (memory_id,),
            ).fetchall()
            replacements = conn.execute(
                "SELECT id,project_id FROM memories WHERE supersedes=%s", (memory_id,),
            ).fetchall()
            links = conn.execute(
                "SELECT l.source_id,l.target_id,l.kind,m.project_id,m.title,m.status "
                "FROM memory_links l JOIN memories m ON m.id=CASE WHEN l.source_id=%s "
                "THEN l.target_id ELSE l.source_id END "
                "WHERE l.source_id=%s OR l.target_id=%s", (memory_id, memory_id, memory_id),
            ).fetchall()
        return {**public(row), "history": [public(r) for r in history],
                "links": [public(r) for r in links if p.admin
                          or (p.all_projects and r["project_id"] is not None)
                          or r["project_id"] in p.project_ids
                          or (r["project_id"] is None and p.allow_shared)],
                "replaced_by": [str(r["id"]) for r in replacements
                                if p.admin or (p.all_projects and r["project_id"] is not None)
                                or r["project_id"] in p.project_ids
                                or (r["project_id"] is None and p.allow_shared)]}

    def link(self, p, memory_id, data):
        with self.db.transaction(p.owner_id) as conn:
            source = self._record(conn, p, memory_id)
            target = self._record(conn, p, data.target_id)
            p.permit(source["project_id"], write=True)
            if memory_id == data.target_id:
                fail(422, "A memory cannot link to itself")
            if target["project_id"] not in (None, source["project_id"]):
                fail(422, "Links cannot implicitly cross project boundaries")
            conn.execute(
                "INSERT INTO memory_links(owner_id,source_id,target_id,kind) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING", (p.owner_id, memory_id, data.target_id, data.kind),
            )
            self._audit(conn, p, "memory.link", memory_id)
        return {"source_id": str(memory_id), "target_id": str(data.target_id), "kind": data.kind}

    def correct(self, p, memory_id, data):
        with self.db.transaction(p.owner_id) as conn:
            old = self._record(conn, p, memory_id, lock=True)
            self._project(conn, p, old["project_id"], write=True)
            if old["revision"] != data.expected_revision or old["status"] == "superseded":
                fail(409, "Stale revision or already superseded; reload before correcting")
            if old["project_id"] != data.replacement.project_id:
                fail(422, "Correction cannot change the memory scope")
            self._snapshot(conn, p, old)
            conn.execute(
                "UPDATE memories SET status='superseded',revision=revision+1,updated_at=now() "
                "WHERE id=%s", (memory_id,),
            )
            result = self._insert_memory(conn, p, data.replacement, memory_id)
            self._audit(conn, p, "memory.correct", memory_id)
        return result

    @staticmethod
    def _snapshot(conn, p, row):
        conn.execute(
            "INSERT INTO revisions(owner_id,memory_id,revision,snapshot) VALUES (%s,%s,%s,%s)",
            (p.owner_id, row["id"], row["revision"], Jsonb(public(row))),
        )

    def status(self, p, memory_id, data):
        with self.db.transaction(p.owner_id) as conn:
            row = self._record(conn, p, memory_id, lock=True)
            p.permit(row["project_id"], write=True)
            if row["revision"] != data.expected_revision or row["status"] == "superseded":
                fail(409, "Stale revision or superseded memory")
            if row["status"] == "expired" and data.status == "active":
                fail(422, "Revalidate expired content using a sourced correction")
            self._snapshot(conn, p, row)
            updated = conn.execute(
                "UPDATE memories SET status=%s,revision=revision+1,updated_at=now() "
                "WHERE id=%s RETURNING *", (data.status, memory_id),
            ).fetchone()
            self._audit(conn, p, "memory.status", memory_id)
        return public(updated)

    def forget(self, p, memory_id):
        p.manage()
        with self.db.transaction(p.owner_id) as conn:
            row = self._record(conn, p, memory_id, lock=True)
            doomed = [r["id"] for r in conn.execute(
                "WITH RECURSIVE doomed(id) AS (SELECT %s::uuid UNION "
                "SELECT l.source_id FROM memory_links l JOIN doomed d ON l.target_id=d.id "
                "WHERE l.kind='derived_from') SELECT id FROM doomed", (row["id"],),
            ).fetchall()]
            conn.execute(
                "INSERT INTO tombstones(memory_id,owner_id,project_id) "
                "SELECT id,owner_id,project_id FROM memories WHERE id=ANY(%s)", (doomed,),
            )
            # Remove full checkpoints referencing this memory, rather than retaining copied text.
            conn.execute("DELETE FROM checkpoints WHERE memory_ids && %s", (doomed,))
            conn.execute("UPDATE captures SET memory_id=NULL WHERE memory_id=ANY(%s)", (doomed,))
            conn.execute("UPDATE memories SET supersedes=NULL WHERE supersedes=ANY(%s)", (doomed,))
            conn.execute("DELETE FROM memories WHERE id=ANY(%s)", (doomed,))
            self._audit(conn, p, "memory.forget", memory_id)
        return {"deleted": True, "id": str(memory_id), "purged_records": len(doomed),
                "historical_backups": "expire separately"}

    def scope_filter(self, p, data):
        if not data.cross_project and data.project_id is None:
            if not (p.admin or p.allow_shared):
                fail(422, "Select a project or explicitly enable cross_project")
            return "project_id IS NULL", []
        clauses, params = [], []
        if data.cross_project:
            if p.admin or p.all_projects:
                clauses.append("project_id IS NOT NULL")
            else:
                clauses.append("project_id=ANY(%s)")
                params.append(list(p.project_ids))
        else:
            p.permit(data.project_id)
            clauses.append("project_id=%s")
            params.append(data.project_id)
        if data.include_shared and (p.admin or p.allow_shared):
            clauses.append("project_id IS NULL")
        return "(" + " OR ".join(clauses) + ")", params

    def list_memories(self, p, project_id=None, limit=100, offset=0):
        from .models import SearchInput
        data = SearchInput(query="list", project_id=project_id, cross_project=project_id is None)
        clause, params = self.scope_filter(p, data)
        with self.db.transaction(p.owner_id) as conn:
            return [public(r) for r in conn.execute(
                f"SELECT * FROM memories WHERE {clause} ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                (*params, limit, offset),
            ).fetchall()]

    def checkpoint(self, p, data):
        with self.db.transaction(p.owner_id) as conn:
            self._project(conn, p, data.project_id, write=True)
            for memory_id in data.memory_ids:
                memory = self._record(conn, p, memory_id)
                if memory["project_id"] not in (None, data.project_id):
                    fail(422, "Checkpoint references a different project")
            key = f"checkpoint:{p.owner_id}:{data.project_id}:{data.session_id}"
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (key,))
            old = conn.execute(
                "SELECT * FROM checkpoints WHERE project_id=%s AND session_id=%s FOR UPDATE",
                (data.project_id, data.session_id),
            ).fetchone()
            if (old["revision"] if old else 0) != data.expected_revision:
                fail(409, "Stale checkpoint revision")
            values = (data.task_ref, data.objective, Jsonb(data.completed), Jsonb(data.verification),
                      Jsonb(data.pending), data.next_action, data.memory_ids)
            if old:
                row = conn.execute(
                    "UPDATE checkpoints SET task_ref=%s,objective=%s,completed=%s,verification=%s,"
                    "pending=%s,next_action=%s,memory_ids=%s,revision=revision+1,updated_at=now() "
                    "WHERE id=%s RETURNING *", (*values, old["id"]),
                ).fetchone()
            else:
                row = conn.execute(
                    "INSERT INTO checkpoints(id,owner_id,project_id,session_id,task_ref,objective,"
                    "completed,verification,pending,next_action,memory_ids) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (uuid4(), p.owner_id, data.project_id, data.session_id, *values),
                ).fetchone()
            self._audit(conn, p, "checkpoint.save", row["id"])
        return public(row)

    def latest_checkpoint(self, p, project_id, task_ref=None, session_id=None):
        p.permit(project_id)
        with self.db.transaction(p.owner_id) as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE project_id=%s "
                "AND (%s::text IS NULL OR task_ref=%s) "
                "AND (%s::text IS NULL OR session_id=%s) ORDER BY updated_at DESC LIMIT 1",
                (project_id, task_ref, task_ref, session_id, session_id),
            ).fetchone()
        return public(row)

    def job(self, p, job_id):
        with self.db.transaction(p.owner_id) as conn:
            row = conn.execute(
                "SELECT id,project_id,memory_id,kind,status,attempts,error,created_at "
                "FROM jobs WHERE id=%s", (job_id,),
            ).fetchone()
        if not row:
            fail(404, "Job not found")
        p.permit(row["project_id"])
        return public(row)

    def jobs(self, p):
        p.manage()
        with self.db.transaction(p.owner_id) as conn:
            return [public(r) for r in conn.execute(
                "SELECT id,project_id,memory_id,kind,status,attempts,error,created_at "
                "FROM jobs ORDER BY created_at DESC LIMIT 100",
            ).fetchall()]

    def retry_job(self, p, job_id):
        p.manage()
        with self.db.transaction(p.owner_id) as conn:
            row = conn.execute(
                "UPDATE jobs SET status='pending',attempts=0,error=NULL,available_at=now() "
                "WHERE id=%s AND status='failed' RETURNING id", (job_id,),
            ).fetchone()
            if not row:
                fail(409, "Job is not failed or does not exist")
        return public(row)
