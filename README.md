# Agent Memory

Repository: [aaronx3011/agents-memory-manager](https://github.com/aaronx3011/agents-memory-manager).

Persistent, multi-project agent memory running locally with Docker. Knowledge is
stored in PostgreSQL outside your repositories, with local semantic embeddings,
keyword search, sourced records, corrections, session checkpoints, MCP tools, and
a browser management interface.

## Start locally

Requirements: Docker Desktop / Docker Compose and Python 3.12+ for setup scripts.
No embedding API key or local Python package installation is needed.

```sh
python3 scripts/configure.py
docker compose up --build -d --wait
docker compose exec app agent-memory bootstrap --directory "$PWD" --repository https://github.com/aaronx3011/agents-memory-manager.git
docker compose exec app agent-memory warmup
```

Open **http://127.0.0.1:8765**. Get the owner login token in your own terminal:

```sh
docker compose exec app agent-memory token
```

The setup script generates random credentials in a private, ignored `.env` file
and never overwrites existing configuration. The first embedding use downloads
MiniLM into a persistent model volume; subsequent embedding runs locally. Initial
download requires internet access. `warmup` loads the model and processes queued
jobs. The app's worker also processes jobs automatically.

The bootstrap registers this project and its user-requested architecture decision.
Register more projects in the UI with their repository URL and/or directory alias.
No memory directories or notes need to be added to those projects.

## What works in the local MVP

- **Five durable knowledge types:** episodic, semantic, procedural, decisions,
  preferences; plus structured session checkpoints.
- **Hybrid recall:** PostgreSQL full-text and pgvector similarity, fused by rank;
  supports paraphrases, exact identifiers, source citations and review flags.
- **Project boundaries:** default project + permitted owner-wide knowledge;
  cross-project retrieval is explicit. Scoped credentials can be read-only,
  read/write, restricted to project IDs, or cover all current/future projects.
- **Memory lifecycle:** idempotent capture, revisions, atomic sourced correction,
  supersession, candidate/disputed/expired states and relationships.
- **Continuity:** save objective, completed work, actual verification, pending
  work and next action; retrieve from a fresh conversation.
- **Background processing:** durable embedding/extraction jobs, leases, retries,
  inspectable failures, keyword-only fallback when embedding is unavailable.
- **Management UI:** project registration, capture, search, provenance/history,
  correction, candidate activation, deletion, scoped key issuance/revocation,
  background job inspection/retry, JSON export.
- **Deletion:** purges canonical text, vectors, revisions, explicitly derived
  memories, and checkpoints referencing deleted IDs. Tombstones support replay
  during restore. Backups have their own retention.
- **Local operations:** database migrations, persistent volumes, health checks,
  backup/restore drill, non-superuser application role, forced owner row security.

The deployment is one local owner's service. It has an owner boundary in the
schema, not a multi-user signup/billing platform. The worker handles that configured
owner. Project grants are enforced by the service; database RLS enforces owner
isolation. The database is not published on a host port. HTTP is loopback-only.

## MCP access

Streamable HTTP endpoint: **http://127.0.0.1:8765/mcp/**. Every request requires
`Authorization: Bearer <token>`. A real MCP client can discover these ten tools:

| Tool | Purpose |
| --- | --- |
| `memory_resolve_project` | Resolve a centrally registered name, UUID, repo URL or directory alias |
| `memory_get_context` | Bounded cited knowledge + resumable checkpoint |
| `memory_search` | Semantic/keyword recall with project/type/state filters |
| `memory_get` | Inspect sources, revision history and relationships |
| `memory_capture` | Idempotently store a sourced typed record |
| `memory_observe` | Store an observation; optionally extract inferred candidates |
| `memory_checkpoint` | Persist resumable work state with revision checks |
| `memory_correct` | Transactionally replace incorrect knowledge |
| `memory_forget` | Owner-only deletion, including explicit derived records |
| `memory_job_status` | Check durable processing receipts |

Tools taking `data` use a nested object. For example, `memory_capture` arguments:

```json
{
  "data": {
    "project_id": "<registered-project-uuid>",
    "type": "decision",
    "title": "Use PostgreSQL for persistent memory",
    "content": "Keep canonical records and vector search in the same transactional store.",
    "sources": [{"kind": "user", "reference": "Dated owner instruction or task URL"}],
    "evidence": "reported",
    "idempotency_key": "unique-observation-key"
  }
}
```

API schemas and interactive documentation: **http://127.0.0.1:8765/docs**.
API calls require the same bearer header; the UI handles it after login.

### Connect OpenCode

Create a personal, non-admin agent key in a private file. The parent directory
must exist. This key can read/write all of this owner's current/future projects
and owner-wide knowledge, but cannot manage credentials, export everything, or
delete memories. Use UI-issued narrower keys for project-limited agents.

```sh
python3 scripts/client_key.py ~/.config/opencode/agent-memory-key
```

Merge the following into your existing global `opencode.json` (keep existing MCP
servers, plugins, providers and instructions):

On this machine this configuration and the private agent key have already been
installed and `opencode mcp list` has confirmed connectivity. The example below is
for reproducing the setup elsewhere.

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "agent-memory": {
      "type": "remote",
      "url": "http://127.0.0.1:8765/mcp/",
      "enabled": true,
      "oauth": false,
      "timeout": 30000,
      "headers": {"Authorization": "Bearer {file:/absolute/path/to/agent-memory-key}"}
    }
  },
  "plugin": [[
    "file:///absolute/path/to/agent-memory/integrations/opencode/memory-plugin.js",
    {"url": "http://127.0.0.1:8765", "tokenFile": "/absolute/path/to/agent-memory-key"}
  ]]
}
```

**Quit and restart OpenCode after configuration changes.** This running session
cannot acquire newly configured MCP tools or hooks without restarting.

The adapter uses documented hooks for per-message scoped recall, labeled reference
context injection, automatic agent-reported outcome capture at idle, and checkpoint
capture before compaction. It preserves richer checkpoints explicitly saved via
MCP. Automatic checkpoints keep verification empty: a prior assistant's claim is
not a verified test result. Direct MCP checkpoints should provide the real checks
and precise next action. Unknown directories must be registered centrally first.

Adapter behavior is covered by Node hook-contract tests; live MCP transport and
two-client continuity are separately tested. Host-specific hook compatibility
should be checked after restarting the installed OpenCode version.

## Optional LLM extraction

Structured capture, checkpoints, embeddings and hybrid search work with no LLM
provider. To extract reusable candidate knowledge from observations automatically,
add these values to `.env`, then recreate the app:

```dotenv
EXTRACTION_BASE_URL=http://host.docker.internal:1234/v1
EXTRACTION_MODEL=your-local-model-id
EXTRACTION_API_KEY=local
```

```sh
docker compose up -d --force-recreate app
```

The endpoint must support OpenAI-compatible chat completions with JSON output.
Extraction creates **inferred candidates**, never verified facts. The owner can
review/activate them in the UI. Each candidate retains scope, provenance and a
`derived_from` relationship. Provider failures are retried visibly; the original
observation remains persisted. An external provider would receive the observation
content; use a local model when content should remain on the machine.

## Tests

The Python suite uses the real Docker PostgreSQL/pgvector database and actual local
embeddings. Each test has its own owner identity and cleans only that owner's data.

```sh
docker compose run --rm app pytest -q -p no:cacheprovider
docker compose run --rm app ruff check --no-cache src tests
npm --prefix integrations/opencode test
npm --prefix tests/browser ci
npm --prefix tests/browser exec -- playwright install chromium
npm --prefix tests/browser test
```

Browser tests require the running local app and its `.env`. They create/delete
clearly labeled synthetic memories in `agent-memory`. Python tests cover scope/RLS,
concurrency, idempotency, sources/history, semantic recall, fallback, budgets,
checkpoints, MCP transport, extraction contracts, job failures and deletion races.

## Backup, restore and persistence

```sh
python3 scripts/backup.py backup
python3 scripts/backup.py verify backups/local/agent-memory/<timestamp>
python3 scripts/backup.py restore backups/local/agent-memory/<timestamp> --database agent_memory_restore_inspect
```

Additional end-to-end checks:

```sh
python3 scripts/verify_restore.py
docker compose run --rm -v "$PWD/scripts:/checks:ro" app python /checks/mcp_smoke.py
```

These verify older-backup deletion replay and two-client network MCP continuity.

Backups contain a PostgreSQL custom-format dump, checksum manifest and content-free
deletion ledger. `verify` restores into a new scratch database, replays subsequent
deletions from the live database, checks exclusion, and removes the scratch database.
`restore` retains it for inspection and never overwrites the working database.

To preserve the latest deletion ledger separately:

```sh
python3 scripts/backup.py ledger backups/latest-deletions.json
python3 scripts/backup.py verify backups/local/agent-memory/<timestamp> --ledger backups/latest-deletions.json
```

Keep the latest ledger alongside off-host backups if recovering after losing the
source host. Local backups are private but unencrypted; scheduled encrypted off-host
backup/ledger replication and production disaster recovery are next-stage work.
Preserve `.env` privately as well; database credentials and owner identity must
match the existing volume. JSON export is an inspection/data portability feature,
not a full operational backup with credentials/history/queue state.

For deployed stacks, every host helper supports explicit environment selection.
Use `--environment development` or `--environment production`; backups carry
owner/environment/project metadata and reject unintended cross-store restores.
See [deployment operations](DEPLOYMENT.md) for release selection, server commands,
CI/SSH setup and migration. The root Compose file remains the local setup.

Use `docker compose stop` / `docker compose start` to pause/resume. Ordinary
`docker compose down` preserves named database/model volumes. `down -v` removes
them and destroys local data. No automatic repository scanning or chat transcript
archiving occurs. The app currently returns top-N search results; browsing records
is paginated. Context budgets are explicit **characters**, not claimed token counts.

## Project documents

- [Deployment strategy based on Agent Task Manager](DEPLOYMENT.md): the existing
  VPN runner, SSH image shipment, environment Compose and HTTPS ingress pattern;
  deployment automation is implemented locally; lists remote rollout prerequisites.
- [Implementation plan and local MVP scope](IMPLEMENTATION_PLAN.md)
- [Initial investigation](RESEARCH.md)
- [Verification record](VERIFICATION.md)

Runtime dependencies are pinned in `requirements.lock`; image bases are pinned by
digest. The initial local release uses psycopg and transactionally applied,
versioned SQL migrations rather than introducing an ORM and migration framework.
