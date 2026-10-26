CREATE TABLE memory_links (
    owner_id uuid NOT NULL,
    source_id uuid NOT NULL,
    target_id uuid NOT NULL,
    kind text NOT NULL CHECK(kind IN ('derived_from','relates_to','contradicts')),
    PRIMARY KEY(source_id,target_id,kind),
    CHECK(source_id<>target_id),
    FOREIGN KEY(owner_id,source_id) REFERENCES memories(owner_id,id) ON DELETE CASCADE,
    FOREIGN KEY(owner_id,target_id) REFERENCES memories(owner_id,id) ON DELETE CASCADE
);
ALTER TABLE memory_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_links FORCE ROW LEVEL SECURITY;
CREATE POLICY owner_isolation ON memory_links
USING(owner_id = nullif(current_setting('memory.owner_id',true),'')::uuid)
WITH CHECK(owner_id = nullif(current_setting('memory.owner_id',true),'')::uuid);
