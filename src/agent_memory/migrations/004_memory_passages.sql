-- Token-aware passage index. Additive: canonical memory text stays untouched.
CREATE TABLE memory_passages (
    id bigserial PRIMARY KEY,
    owner_id uuid NOT NULL,
    memory_id uuid NOT NULL,
    project_id uuid,
    revision integer NOT NULL,
    ordinal integer NOT NULL,
    token_count integer NOT NULL,
    text text NOT NULL,
    content_hash text NOT NULL,
    embedding vector(384),
    embedding_model text,
    created_at timestamptz NOT NULL DEFAULT now(),
    search tsvector GENERATED ALWAYS AS (
      setweight(to_tsvector('english', text), 'B')
    ) STORED,
    UNIQUE(memory_id, ordinal),
    FOREIGN KEY(owner_id, memory_id) REFERENCES memories(owner_id, id) ON DELETE CASCADE,
    FOREIGN KEY(owner_id, project_id) REFERENCES projects(owner_id, id)
);
CREATE INDEX memory_passages_scope ON memory_passages(owner_id, project_id);
CREATE INDEX memory_passages_model ON memory_passages(embedding_model);
DO $$
BEGIN
  EXECUTE 'ALTER TABLE memory_passages ENABLE ROW LEVEL SECURITY';
  EXECUTE 'ALTER TABLE memory_passages FORCE ROW LEVEL SECURITY';
  EXECUTE 'CREATE POLICY owner_isolation ON memory_passages USING '
          '(owner_id = nullif(current_setting(''memory.owner_id'', true), '''')::uuid) '
          'WITH CHECK (owner_id = nullif(current_setting(''memory.owner_id'', true), '''')::uuid)';
END $$;
