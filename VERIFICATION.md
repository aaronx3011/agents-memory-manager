# Local MVP and deployment verification

2026-10-26 · Tasks #106–#108 and #115 · Python 3.12 / PostgreSQL 17 / pgvector / ARM64 Docker

## Executed checks

| Check | Result |
| --- | --- |
| Real PostgreSQL/pgvector Python + deployment suite | **34 passed**; includes isolated synthetic owner identities and host-operation tests |
| OpenCode adapter Node hook-contract suite | **2 passed** |
| Chromium/Playwright owner workflow | **1 passed** |
| Ruff on Python service, tests and operating scripts | **Passed** |
| Real MCP SDK network check | **Passed**: ten tools discovered; independent clients capture and recover checkpoint/context |
| OpenCode CLI connection check | **Passed**: `opencode mcp list` reports both agent-memory and task-coordinator connected |
| Global OpenCode configuration | **Passed** published JSON Schema validation |
| Original database restart | **Passed**: registered project and sourced architecture decision persisted |
| App image rebuild/container recreation | **Passed** with original database retained |
| Final combined app/database restart | **Passed**: project, sourced decision, release checkpoint and hybrid recall survived |
| Clean-volume initialization | **Passed** in isolated `agent-memory-clean` Compose project; migrations completed with zero records; scratch volumes removed |
| PostgreSQL custom-format backup/checksum/restore | **Passed** into a separate scratch database |
| Older-backup deletion replay | **Passed**: create fixture, back up, delete, restore older snapshot, replay ledger, assert fixture absent |
| Environment-specific deployment harness | **Passed**: fresh development + no-published-port production, second synthetic-SHA update, automatic pre-update backup, scratch restore and restart persistence |
| Production networking | **Passed locally**: app joins disposable proxy network; DB does not; neither publishes a production host port |
| Configurable browser target | **Passed** Chromium workflow against a disposable development stack on a random non-default port with its own private env file |
| Workflow validation | **Passed** actionlint 1.7.12 (custom runner label configured); `bash -n scripts/deploy.sh` passed |
| Backward-compatible local operations | **Passed** retained existing private configuration; explicit local Target selection and environment-bound backup/deletion-replay restore |

The Python suite exercises real local MiniLM embeddings for paraphrase recall,
exact identifier recall, scoped keyword/vector queries, owner-wide grants, future
project grants, direct-ID/job isolation, forced owner RLS under a non-superuser
role, credentials/revocation, idempotency, correction history and concurrent stale
edits, freshness and inactive filters, character budgets, session recovery, MCP
JSON-RPC transport, optional extraction adapter contracts, derived-record purge,
retry/lease exhaustion, and deletion versus in-flight embedding.

The browser test logs in, creates a sourced memory, inspects provenance, corrects
it, searches using hybrid recall, deletes current and superseded fixtures, and
opens background job inspection. It checks for JavaScript page errors.

## Worker deployment (2026-10-26)

Deployed to the self-hosted worker `lesbian` (10.8.0.6, Debian 13, x86_64), because
the owner requires the memory service to run on the self-hosted worker machine, not
the Mac. The service runs under `~/agent-memory` (sudo is password-protected, so
`/opt` was not used) as Compose project `agent-memory-dev`.

| Check | Result |
| --- | --- |
| x86_64 images built on the target | `agent-memory:7d10c17…` and `agent-memory-db:7d10c17…` |
| Existing owner/project/memory/checkpoint migrated | **Passed**: 1 project, 1 memory, 1 checkpoint, 3 migrations |
| `scripts/deploy.sh development <SHA>` on the worker | **Passed**: healthy app+DB, warmup, two-client MCP smoke |
| Mac → VPN health and authenticated API | **Passed** |
| Existing non-admin OpenCode agent key against remote | **Passed** |
| OpenCode MCP reconnection | **Passed**: `opencode mcp list` shows `agent-memory connected` |
| Network exposure | App listens only on `10.8.0.6:8765`; DB unpublished |
| Local Mac runtime removed | Containers, volumes, network, `.env`, `.verification` and backups removed; port 8765 closed |
| Private backup moved off the Mac | Copied to `~/agent-memory/backups` on the worker before local deletion |

Not verified/configured: HTTPS ingress, scheduled off-host backup replication, and
the GitHub self-hosted `ship` job (no runner registered for this repository yet).
The service is VPN-only over WireGuard at the time of writing.

## Deployment asset verification (#115)

Development/production Compose and deployment helpers were exercised on disposable
local Docker stacks using synthetic SHA image aliases, not fabricated Git commits.
Both layouts passed initial deploy, authenticated two-client MCP smoke, an update
with automatic backup of the previous verified release, scratch restore, release
marker checks and database/app restart persistence. Test stacks, volumes, proxy
network and synthetic image aliases were removed without selecting the existing
local store. The browser workflow was additionally exercised on a non-default
development port with selected fixture credentials.

The new unit checks cover explicit Compose/env/project selection, isolation from
ambient local credentials, missing/private configuration, full-SHA requirements,
unverified release markers, owner/environment restore rejection, service-origin
validation, project identity alias preservation and done/blocked pipeline reports.

```sh
docker compose build app db
python3 scripts/verify_deployment.py
python3 scripts/verify_deployment.py --only development --browser
```

The supplied GitHub repository is
`https://github.com/aaronx3011/agents-memory-manager`. Local `main` and `origin`
are configured. At inspection the remote was empty/public with zero runners,
environments, Actions secrets and variables. Workflows were validated locally;
no GitHub workflow run, SSH shipment, external ingress/TLS check or remote
production release is claimed by these tests. Initial publication and the
documented infrastructure settings remain rollout prerequisites.

## Issue found and fixed during live testing

A network smoke check exposed a deadlock between canonical memory deletion and
embedding completion. The worker previously locked the job before the memory;
deletion locked the memory before its cascading job deletion. Both paths now
lock the canonical memory before the job. A regression test holds a database
deletion lock during embedding completion and checks that cascading deletion can
complete without waiting on the worker's job lock. The full suite and network
smoke check passed after rebuilding the fix.

The initial bind-mounted database initialization script also failed on this Docker
host. The database image now copies the initialization script with explicit
non-executable permissions so PostgreSQL sources it during initialization, avoiding
the host bind-mount execution restriction.

## Reproduce

```sh
docker compose up --build -d --wait
docker compose exec app agent-memory bootstrap
docker compose exec app agent-memory warmup
docker compose run --rm app pytest -q -p no:cacheprovider
docker compose run --rm -v "$PWD/scripts:/app/scripts:ro" app ruff check --no-cache src tests scripts
npm --prefix integrations/opencode test
npm --prefix tests/browser ci
npm --prefix tests/browser exec -- playwright install chromium
npm --prefix tests/browser test
docker compose run --rm -v "$PWD/scripts:/checks:ro" app python /checks/mcp_smoke.py
python3 scripts/verify_restore.py
opencode mcp list
```

Browser/MCP/restore scripts use clearly labeled temporary records and remove them
after successful verification. The restore drill retains its private ignored
backup artifact but removes its scratch database. Test failures should be resolved
before treating the relevant workflow as verified.

## Deployment handoff

- UI: `http://127.0.0.1:8765`
- API schema: `http://127.0.0.1:8765/docs`
- MCP: `http://127.0.0.1:8765/mcp/`
- Canonical storage: Docker volume `agent-memory_memory-db`.
- Local model cache: Docker volume `agent-memory_memory-models`.
- Owner configuration: private project `.env`; do not regenerate it for an existing volume.
- Agent key: `~/.config/opencode/agent-memory-key`, issued without management privileges.
- Global OpenCode MCP and adapter configuration installed; quit and restart OpenCode
  to load it in new agent sessions. The CLI connection check does not prove the
  running conversation has reloaded tools or every host-version hook has fired.
- A release handoff with executed checks and the next action is persisted as a
  checkpoint in the service, not a repository memory file. Its session identifier
  is `local-mvp-release-2026-10-26` and task reference is `coordinator:108`.

## Local-release boundaries

The core local service, semantic recall, structured capture, checkpoints and owner
UI work without an LLM API key. Automatic extraction was contract-tested with an
HTTP mock; no real extraction provider is configured by default. The OpenCode
adapter captures labeled agent-reported outcomes and leaves verification empty
unless an agent explicitly records checks through the checkpoint tool.

Encrypted scheduled off-host backups/deletion-ledger replication, remote hosting,
multi-user administration, advanced scheduled consolidation, and tokenizer-specific
context budgets belong to the next stage. Local backup files are private but
unencrypted. The test environment emits one upstream Starlette/httpx TestClient
deprecation warning; all tests pass with the pinned runtime.
