# Persistent Agent Memory Platform — Implementation Plan

Task #105 · Revised 2026-10-26 · Local implementation tracked by Tasks #106–#108

Deployment assets: Task #115, repository
<https://github.com/aaronx3011/agents-memory-manager>; operational instructions and
publication/infrastructure prerequisites are in [DEPLOYMENT.md](DEPLOYMENT.md).

## Local MVP delivery scope

The owner authorized implementation and Docker-backed local verification. The
local release implements M1–M3 and the local management portion of M4: central
PostgreSQL/pgvector, real local MiniLM embeddings, hybrid search, scoped auth,
memory types/provenance/revisions, checkpoints, durable jobs, MCP, a browser UI,
and an OpenCode adapter. Backups and scratch-database restore drills are included.

Concrete choices: psycopg with versioned transactional SQL migrations; a background
worker thread using a durable PostgreSQL queue; local fastembed/ONNX embeddings;
optional OpenAI-compatible extraction; plain browser UI. Dependencies and Docker
base images are pinned. The local service has one configured owner; owner RLS and
project grants are distinct enforcement layers. Context budgets use characters.

M5 remote hosting, encrypted off-host backup/ledger replication, advanced scheduled
consolidation/review, tokenizer-specific budgets and a multi-user administration
system remain next-stage scope after the local MVP. The remainder documents the
target architecture and work packages; see README.md for actual supported behavior
and VERIFICATION.md for executed checks.

## 1. Goal and corrected direction

Build one persistent memory system for the owner's projects and agents. Memory
lives in a central database outside project repositories and survives new
conversations, agent restarts, container recreation, and switching machines when
connected to the same deployment. Agents access it through MCP; the owner can
search, inspect, correct, and delete memories through a management interface.

This revision replaces the previous file-first implementation plan following the
owner's clarification. Markdown files are documentation or optional exports, not
the memory backend. A manual-file pilot is no longer a prerequisite.

The [first investigation](RESEARCH.md) remains useful for provenance, freshness,
correction, trust boundaries, and keeping task state in its authoritative system.
Its proposed file layout and database deferral are superseded by this plan.

## 2. Recommended architecture

```text
Coding agents / other MCP clients            Owner management UI
                |                                  |
        Authenticated MCP gateway           Authenticated HTTP API
                |                                  |
                +-------- Memory service ----------+
                          |           |
                   PostgreSQL      Background worker
                   + pgvector      - embedding generation
                   + full-text     - extraction / consolidation
                   + relations     - freshness / maintenance
                          |
                   Persistent volume
                   + encrypted off-host backups
```

Deploy the service, worker, and database together with Docker Compose initially.
Use the same application artifact for local development and a self-hosted server.
For shared access across machines, run one authoritative server deployment; each
client connects to it. Separate local databases do not synchronize automatically.
Use TLS for remote client connections and keep the database reachable only by
the service/worker and designated administration paths.

### Technology choices

| Component | Proposed choice | Reason |
| --- | --- | --- |
| Durable storage | PostgreSQL with pgvector | Transactions, structured records, full-text and vector search in one system |
| Service | Python 3.12, FastAPI, psycopg, versioned SQL migrations | Typed APIs, transactions, shared domain layer; concrete local MVP choice |
| Agent interface | Official Python MCP SDK; Streamable HTTP | Remote clients share a single service; optional stdio bridge for clients that need it |
| Jobs | PostgreSQL-backed queue / transactional outbox and a worker process | Durable retries without adding Redis to the first release |
| Embeddings | Configurable provider adapter | Semantic recall without coupling records to a provider |
| Extraction | Configurable structured-output LLM adapter | Turn bounded session observations into useful memory candidates |
| Management | Small server-rendered web UI initially | Search, inspect history, correct, delete, and view ingestion/job state |
| Operations | Compose, persistent database volume, health checks, backup/restore scripts | A reproducible system with tested persistence |

Pin tested dependency/image versions during implementation. Benchmark before
choosing approximate vector indexes; exact scoped vector search is a valid initial
implementation for a personal dataset. Do not start with separate vector and graph
databases: PostgreSQL supports the initial retrieval and relationship requirements.

## 3. Memory types and their behavior

Memory type describes how knowledge is used, not a separate database product.

| Type | Examples | Capture and retrieval |
| --- | --- | --- |
| Episodic | Investigation outcome, debugging session, attempted approach and result | Summarize session events; recall by task, time, and similarity |
| Semantic | Architecture, project terminology, verified environment constraints | Extract durable facts with evidence; retrieve by subject and meaning |
| Procedural | Tested deployment workflow, repeatable fix, required command sequence | Retain prerequisites and successful checks; invalidate on dependency changes |
| Decisions | Chosen approach, rejected alternative, rationale | Link to affected entities, source task, and replacement decisions |
| Preferences | Explicit user-wide or project-specific conventions | Preserve intended scope; distinguish user statements from inferred patterns |
| Session checkpoints | Objective, completed steps, open work, artifacts, next action | Persist compact resumable state before context compaction and at handoff |

Working context stays in the current agent session; a checkpoint persists only
the useful resumable subset. Links between memories and entities provide
graph-like traversal, for example project -> service -> decision -> incident ->
resolution. This is a relational knowledge graph, not a promise of a separate
graph database or unrestricted multi-hop reasoning in the first milestone.

## 4. Scope, identity, and project resolution

- Every row belongs to an owner/workspace. Start with one owner, while retaining
  explicit ownership in the schema. Authentication resolves the owner server-side.
- Memories are either project-scoped or owner-wide. Project queries include the
  selected project and permitted owner-wide records; all results label their scope.
- Owner-wide preferences can apply across projects. Facts from another project
  require an explicit cross-project search; they are not silently mixed in.
- Register projects centrally with a stable UUID, name, repository URLs, and
  optional machine-specific directory aliases. This needs no per-project files.
- Resolve a project from a registered repository identity or explicit project ID.
  An ambiguous or unknown directory must not silently create or select a project.
- Credentials have allowed project IDs and read/write/manage capabilities. Search,
  direct ID lookup, relationships, checkpoints, jobs, and UI endpoints all enforce
  the same policy before returning data. An agent-supplied owner ID is not authority.
- Use scoped SQL queries and PostgreSQL row-level policies as defense in depth;
  application roles must not bypass those policies. Reset request identity between
  pooled connections and test authorization with the actual deployment roles.

Code and live task state remain in Git and the coordinator. Memories may retain
dated observations and links, but must re-query those systems before acting on
current branch, ownership, task status, or dependencies.

## 5. Data model

Use migrations and server-generated UUIDs. Core tables:

| Table | Purpose and essential fields |
| --- | --- |
| owners, principals, credentials | Owner identity, agent/user identity, hashed credential material and grants |
| projects, project_aliases | Stable project identity, repository URL aliases, machine/path aliases |
| memories | Owner, nullable project, type, title, content, structured metadata, evidence level, status, revision, content hash, creation/observation/verification/review dates |
| memory_sources | Memory ID, source kind, reference, optional commit/version, observation time, minimal supporting excerpt |
| memory_revisions | Prior content and provenance for normal correction history; same access scope as the memory |
| entities, memory_entities | Scoped subjects such as a service, dependency, component, or convention |
| memory_links | Typed links: supersedes, contradicts, derived_from, relates_to; scoped foreign-key integrity |
| sessions, checkpoints | Agent/session/project, external task reference, checkpoint revision and resumable summary |
| memory_embeddings | Memory revision, provider/model/version, dimensions, content hash, vector |
| ingestion_events, jobs | Idempotency key, bounded capture payload, job state, retries, lease, error category |
| audit_events, deletion_tombstones | Actor, operation, target IDs, timestamp; no retained deleted content |

Statuses: `candidate`, `active`, `superseded`, `expired`, `disputed`. Evidence:
`inferred`, `reported`, `verified`. A verification date requires supporting
evidence; LLM extraction is not verification. Past review dates produce a visible
staleness flag rather than automatic truth or automatic deletion.

Edits require an expected revision. Supersession updates old and replacement
records and links in one transaction. Concurrent stale edits fail explicitly.
Exact capture duplicates use scoped content hashes and idempotency keys; similar
records become consolidation candidates, not automatic destructive merges.

Use one configured embedding dimension per index generation. Model/dimension
changes build a separate generation and backfill it before switching queries;
never compare vectors from incompatible models. Canonical text remains usable
through keyword search during embedding failures or migrations.

## 6. Capture, learning, and session continuity

Database persistence alone does not make agents remember. Ship a thin harness
adapter that uses the service at useful lifecycle points:

1. **Session start:** identify project and query live task state; request a context
   bundle for the current objective plus the most relevant checkpoint.
2. **During work:** capture material user corrections, decisions, validated fixes,
   and constraints as structured observations. Retrieve again when the topic changes.
3. **Before compaction / at handoff:** persist a checkpoint with completed work,
   actual verification, artifact references, unresolved issues, and next action.
4. **After capture:** the worker extracts and deduplicates candidates, attaches
   provenance, and queues embeddings. Return a durable receipt and job state.
5. **Next session:** retrieve relevant knowledge and the resumable checkpoint;
   check current sources where freshness matters.

Use available OpenCode lifecycle hooks after verifying their actual APIs. If a
hook does not exist, define an explicit tool-call workflow for that event and
identify that limitation in the UI/runbook. A generic MCP server cannot by itself
force every client to call tools or supply conversation context.

Automatic capture stores bounded, relevant observations, not an indefinite raw
transcript. Directly sourced outcomes can become active with their evidence label.
Ambiguous extraction remains a candidate; conflicting claims remain disputed until
resolved. User-stated preferences are reported evidence, not inferred facts.
Shared owner-wide scope must be explicit, not guessed from one project's usage.

When LLM extraction is unavailable, keep the accepted observation/checkpoint and
retry the job; do not claim extraction succeeded. When the memory server is
unavailable, report capture failure and continue work with current context. An
optional encrypted client retry spool can be added later; the initial client must
not pretend that an unsent observation is persisted.

## 7. Hybrid retrieval and context assembly

1. Authenticate and resolve permitted project/owner-wide scopes.
2. Filter inactive/deleted records and apply type, entity, task, and time filters.
3. Generate independent full-text and vector candidate sets within those scopes.
4. Fuse rankings using reciprocal rank fusion; boost explicit entity matches,
   applicable evidence, and freshness. Do not equate similarity with truth.
5. Expand a bounded set of useful relationships, rechecking scope and status.
6. Deduplicate and assemble a context bundle within the client's token budget.

Return citations with memory ID/revision, scope, source reference, evidence label,
verification/review dates, and unresolved conflicts. Keep owner preferences,
project knowledge, procedures, and resumable session state separately labeled.
Use a specified tokenizer for the budget; report an estimate when the client model
has no supported tokenizer. Include metadata in the budget and preserve citations.

On embedding-provider failure, explicitly report keyword-only retrieval. A new
active memory is keyword-searchable immediately after commit even if embeddings are
pending. Retrieved text remains reference data and cannot grant permissions or
override current instructions.

## 8. Proposed MCP tool surface

Names and schemas below are contracts to implement, not tools currently available.

| Tool | Contract |
| --- | --- |
| `memory_resolve_project` | Resolve registered repo/directory identity or return explicit ambiguity |
| `memory_get_context` | Project + objective + optional task + budget -> bounded cited context and checkpoint |
| `memory_search` | Query + permitted scopes + filters -> hybrid results, cursor, retrieval mode |
| `memory_get` | ID + optional revision -> record, sources, relationships, permitted history |
| `memory_capture` | Project/scope + typed observation + sources + idempotency key -> durable ID/receipt and processing state |
| `memory_checkpoint` | Session/task + structured handoff + expected revision -> committed checkpoint |
| `memory_correct` | ID + replacement + evidence + expected revision -> transactional correction/supersession |
| `memory_forget` | Authorized target -> immediate retrieval exclusion and purge job/receipt |
| `memory_job_status` | Receipt/job ID -> authorized processing state and safe failure details |

Project registration, credential management, export, bulk operations, and
consolidation management live in the admin API/UI. MCP and HTTP share one domain
service, authorization implementation, and transactional mutation path.

## 9. Persistence, maintenance, and inspectability

- A named PostgreSQL volume persists across application/container recreation.
  Container deletion is not equivalent to a backup or cross-machine replication.
- Back up PostgreSQL daily to encrypted storage outside the database host. Initial
  targets: recovery point <=24 hours and restore within four hours, to be verified
  with a measured restore drill before calling the deployment production-ready.
- Capture/checkpoint tools acknowledge persistence only after transaction commit;
  asynchronous processing has a separately visible state. Leased jobs retry with
  backoff, capped attempts, and an inspectable failed-job state.
- A management UI exposes project filters, hybrid search, provenance/history,
  corrections, delete/export, stale/disputed records, and capture/embedding failures.
- Transactional deletion excludes records immediately and purges content from
  revisions, sources, embeddings, checkpoints, ingestion payloads, and derived
  summaries referencing them. Invalidate or rebuild derived content; do not leave
  a copy hidden in a generated summary. Job completion rechecks deletion state so
  an in-flight worker cannot reintroduce deleted content.
- Retain content-free deletion tombstones and replay them after a backup restore
  before reopening access. Replicate the deletion ledger outside the database host
  before acknowledging purge completion so a restore of an older backup can apply
  subsequent deletions. Define backup expiry and tombstone retention together;
  report historical backup expiry separately from active-data purge completion.
- Keep operational logs content-free where possible. Retain capture payloads only
  for processing/retry and a configured short diagnostic window. Make retention
  per memory class configurable; do not expire durable facts solely due to age.
- Surface ingestion failures, retrieval latency, queue age, embedding coverage,
  database/backup health, and restore-test results.

## 10. Implementation backlog and dependency gates

### M1 — Persistent service foundation

Create the service package, Compose deployment, PostgreSQL/pgvector migrations,
project registry, scoped authentication, basic CRUD, revision checks, audit events,
and backup/restore commands. Proposed layout:

```text
agent-memory/
  compose.yaml
  pyproject.toml
  migrations/
  src/agent_memory/
    domain/     # Records, provenance, revisions, scope policy
    api/        # HTTP and MCP transports
    storage/    # SQL queries, transactions, full-text/vector repositories
    retrieval/  # Hybrid ranking and context assembly
    workers/    # Durable jobs, extraction, embeddings, consolidation
    adapters/   # Provider and harness integration boundaries
    web/        # Owner management views
  tests/        # Unit, PostgreSQL integration, end-to-end evaluation fixtures
```

**Acceptance:** register two projects, store sourced memories, restart/recreate
application and database containers without removing the volume, and retrieve the
same committed records. Unauthorized reads/writes and cross-owner lookups fail.
Concurrent edits produce an explicit revision conflict. No project memory files
are created.

### M2 — Semantic and keyword recall

**Depends on M1.** Add durable embedding jobs, provider configuration, PostgreSQL
full-text search, scoped vector queries, hybrid fusion, citations, relationship
links, and bounded context assembly. Add exact-hash duplicate prevention.

**Acceptance:** recall by paraphrase and by exact technical identifier; show
sources and staleness; exclude unrelated project records; support explicit
authorized cross-project search. Keyword search works while embeddings are down,
and provider/dimension migration does not mix incompatible vectors.

### M3 — Agent continuity and automatic capture

**Depends on M2.** Implement the MCP contracts, extraction jobs, session/checkpoint
storage, and the first OpenCode adapter. Verify hook support before implementing
automatic event handling; use documented tool workflows for unsupported hooks.

**Acceptance:** in a real client, session A completes work and saves a checkpoint;
session B recovers the correct project context and resumes without the old chat.
A newly captured fix is retrieved in a later related task. Provider failures,
client retries, duplicate delivery, and service outages have truthful receipts
and no false persistence claims.

### M4 — Full memory management and learning lifecycle

**Depends on M3.** Deliver the owner UI, correction/supersession, scoped preferences,
entity navigation, disputed-record handling, conservative consolidation, export,
and deletion through all derived representations. Add scheduled stale review jobs.

**Acceptance:** the owner can inspect why a memory exists, correct it, see the
replacement in retrieval, and delete it across canonical and derived data. A
contradiction is surfaced rather than silently overwritten. Owner-wide preferences
apply across projects while project-local rules remain local.

### M5 — Reliability and multi-project rollout

**Depends on M4.** Deploy the authoritative shared instance, register the owner's
projects centrally, configure client credentials, complete restore/failure drills,
and evaluate retrieval/context quality against realistic multi-project scenarios.

**Acceptance:** two independent clients use the same durable store, concurrent
writes preserve integrity, host recovery meets the measured targets, deletions
remain deleted after restore, and agents continue correctly across session and
project switches. No repository-specific memory directory is required.

M1–M3 form the first end-to-end release. M4–M5 complete the management and
operational capabilities expected of the full system; they are part of the scope,
not replacements for persistence or semantic recall.

## 11. Verification strategy

Run integration tests against real PostgreSQL/pgvector, not a SQLite substitute.
Use synthetic records for automated tests and real agent sessions for continuity
evaluation. Include:

- Scope checks before both candidate searches, direct ID reads, link expansion,
  job receipts, and admin endpoints; actual database-role isolation checks.
- Transaction rollback, optimistic concurrency, duplicate delivery, worker lease
  expiry, retries, embedding outages, and deletion-versus-worker races.
- Corrected/superseded/expired/disputed records, conflicting sources, stale
  procedures, and injection-like stored text as untrusted reference data.
- A labeled query set with paraphrases, exact identifiers, cross-project distractors,
  and expected source citations; compare hybrid, keyword-only, and vector-only
  recall with context size and latency. Set performance targets from the measured
  baseline rather than invented throughput promises.
- Persistence through restarts and a full backup/restore including deletion
  tombstone replay before clients reconnect.

Tooling checks should include `pytest` plus formatting/type checks once the
package exists. No runtime tests have been run for this planning-only revision.

## 12. Deployment decisions and next executable step

Use the [Agent Task Manager-aligned deployment strategy](DEPLOYMENT.md): the
existing VPN-connected self-hosted runner, commit-tagged app/database image
shipment over SSH, environment-specific Compose and existing HTTPS ingress.
Keep the local root Compose environment for development and production memory
outside repositories. The deployment guide distinguishes the coordinator's live
development environment from its separate manual production template and lists
the implemented memory-specific automation and remaining remote prerequisites. Provider adapters allow
local models or external APIs; confirm whether project content may leave the host
before selecting an external extraction provider.

The local M1–M3 implementation and local management work are tracked in coordinator
tasks #106–#108. The `agent-memory` project is bootstrapped in the service; automated
tests register additional isolated projects and demonstrate multi-project behavior.
After local verification, use real project sessions to evaluate recall quality
before moving to M5's remote deployment and operational targets.
