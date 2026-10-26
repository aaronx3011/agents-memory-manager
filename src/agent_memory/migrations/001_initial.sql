CREATE TABLE projects (
    id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    name text NOT NULL,
    repo_url text,
    aliases jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(owner_id, name), UNIQUE(owner_id, id)
);
CREATE TABLE credentials (
    id uuid PRIMARY KEY, owner_id uuid NOT NULL, name text NOT NULL,
    token_hash text NOT NULL UNIQUE, project_ids uuid[] NOT NULL DEFAULT '{}',
    allow_shared boolean NOT NULL DEFAULT false, can_write boolean NOT NULL DEFAULT false,
    revoked boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE memories (
    id uuid PRIMARY KEY, owner_id uuid NOT NULL, project_id uuid,
    type text NOT NULL CHECK(type IN ('episodic','semantic','procedural','decision','preference')),
    title text NOT NULL, content text NOT NULL, sources jsonb NOT NULL,
    evidence text NOT NULL CHECK(evidence IN ('inferred','reported','verified')),
    status text NOT NULL CHECK(status IN ('candidate','active','superseded','expired','disputed')),
    revision integer NOT NULL DEFAULT 1, created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
    verified_at timestamptz, review_after timestamptz, supersedes uuid,
    tags text[] NOT NULL DEFAULT '{}', content_hash text NOT NULL,
    embedding vector(384), embedding_model text,
    search tsvector GENERATED ALWAYS AS (
      setweight(to_tsvector('english', title), 'A') ||
      setweight(to_tsvector('english', content), 'B')
    ) STORED,
    UNIQUE(owner_id, id),
    FOREIGN KEY(owner_id, project_id) REFERENCES projects(owner_id, id),
    FOREIGN KEY(owner_id, supersedes) REFERENCES memories(owner_id, id)
);
CREATE INDEX memories_search ON memories USING gin(search);
CREATE INDEX memories_scope ON memories(owner_id, project_id, status);
CREATE TABLE revisions (
    id bigserial PRIMARY KEY, owner_id uuid NOT NULL, memory_id uuid NOT NULL,
    revision integer NOT NULL, snapshot jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(owner_id, memory_id) REFERENCES memories(owner_id, id) ON DELETE CASCADE,
    UNIQUE(memory_id, revision)
);
CREATE TABLE captures (
    id uuid PRIMARY KEY, owner_id uuid NOT NULL, actor text NOT NULL,
    idempotency_key text NOT NULL, payload_hash text NOT NULL, memory_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(owner_id, actor, idempotency_key)
);
CREATE TABLE checkpoints (
    id uuid PRIMARY KEY, owner_id uuid NOT NULL, project_id uuid NOT NULL,
    session_id text NOT NULL, task_ref text, objective text NOT NULL,
    completed jsonb NOT NULL, verification jsonb NOT NULL, pending jsonb NOT NULL,
    next_action text NOT NULL, memory_ids uuid[] NOT NULL DEFAULT '{}',
    revision integer NOT NULL DEFAULT 1, updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(owner_id, project_id, session_id),
    FOREIGN KEY(owner_id, project_id) REFERENCES projects(owner_id, id)
);
CREATE TABLE jobs (
    id uuid PRIMARY KEY, owner_id uuid NOT NULL, project_id uuid, memory_id uuid,
    kind text NOT NULL CHECK(kind IN ('embedding','extraction')),
    payload jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','running','done','failed')),
    attempts integer NOT NULL DEFAULT 0, available_at timestamptz NOT NULL DEFAULT now(),
    leased_at timestamptz, lease_id uuid, error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY(owner_id, project_id) REFERENCES projects(owner_id, id),
    FOREIGN KEY(owner_id, memory_id) REFERENCES memories(owner_id, id) ON DELETE CASCADE
);
CREATE INDEX jobs_pending ON jobs(owner_id, status, available_at);
CREATE TABLE audit_events (
    id bigserial PRIMARY KEY, owner_id uuid NOT NULL, actor text NOT NULL,
    action text NOT NULL, target_id uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE tombstones (
    memory_id uuid PRIMARY KEY, owner_id uuid NOT NULL, project_id uuid,
    deleted_at timestamptz NOT NULL DEFAULT now()
);
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['projects','credentials','memories','revisions','captures',
                          'checkpoints','jobs','audit_events','tombstones']
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('CREATE POLICY owner_isolation ON %I USING (owner_id = nullif(current_setting(''memory.owner_id'', true), '''')::uuid) WITH CHECK (owner_id = nullif(current_setting(''memory.owner_id'', true), '''')::uuid)', t);
  END LOOP;
END $$;
