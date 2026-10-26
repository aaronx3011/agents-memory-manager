# Agent Memory Management — Initial Investigation

Initial planning guide · Task #104 · 2026-10-26

## Purpose

Agent memory should preserve useful knowledge across sessions without turning
old conversations, guesses, or retrieved text into unquestioned instructions.
The goal is reliable continuity: an agent can recover the relevant context,
explain where it came from, check whether it is still valid, and resume work.

This document proposes a practical, tool-independent design. The directory
layout, record format, budgets, and retention periods below are starting points,
not an implemented memory service.

## Current implementation direction

The owner clarified that the goal is a persistent memory system shared across
projects, with memory stored outside repositories. The revised
[Implementation Plan](IMPLEMENTATION_PLAN.md) proposes a central PostgreSQL/pgvector
service, multiple memory types, hybrid retrieval, MCP access, automatic capture,
and an owner management interface.

That plan supersedes this investigation's file-first storage recommendation and
database deferral. The sections below remain the original investigation; their
provenance, freshness, scope, and correction principles still inform the system.

## 1. Core principles

1. **Keep authoritative state in its owning system.** Code belongs in the
   repository; task status belongs in the task coordinator; secrets belong in a
   secret store. Memory holds concise context and references to those systems.
2. **Save decisions and reusable facts, not entire transcripts.** Record the
   reason behind a choice, evidence, constraints, and what to do next.
3. **Separate facts, decisions, and hypotheses.** An agent inference must never
   silently become a confirmed user preference or verified project fact.
4. **Scope every memory.** A project-specific convention must not leak into an
   unrelated project or a different user's context.
5. **Make freshness explicit.** Track when information was observed, verified,
   superseded, and when it should be rechecked.
6. **Retrieve selectively.** A small relevant context is more useful than loading
   every historical note at session start.
7. **Support correction and deletion.** Users and maintainers must be able to
   inspect, amend, expire, and remove retained information.
8. **Treat memory as data.** Stored or retrieved text does not gain permission to
   override current instructions or authorize actions.

## 2. Memory layers

| Layer | Contents | Lifetime and authority |
| --- | --- | --- |
| Working context | Current request, relevant files, temporary hypotheses, recent tool results | Current session; discard or summarize at handoff |
| Operational state | Task owner, progress, dependencies, blockers | Live task system; re-read before acting |
| Episodic memory | A concise account of a completed investigation or work session | Retain while useful; link to artifacts and evidence |
| Semantic memory | Stable project facts, explicit preferences, terminology, architectural constraints | Durable but periodically verified |
| Procedural memory | Tested workflows, commands, troubleshooting steps | Versioned documentation; revalidate when dependencies change |

Do not maintain independent competing copies of live task status. A handoff can
say “blocked as of this timestamp,” but the next session must consult the task
system for the current state.

## 3. What deserves durable storage?

Store an item only if it is likely to improve a future decision, has a clear
scope, and can be supported by a source or explicitly labeled as uncertain.

**Good candidates**

- An architectural decision with its rationale and tradeoffs.
- A verified environment constraint that is expensive to rediscover.
- An explicit user preference, within the scope the user intended.
- A reproducible failure and the verified resolution.
- A useful handoff: artifacts changed, checks performed, blockers, next action.

**Keep temporary or omit**

- Raw command output, repeated status messages, and full chat transcripts.
- Speculation that has no immediate follow-up or supporting evidence.
- Facts that are cheap to query and change frequently, such as branch status.
- Passwords, API keys, job tokens, private keys, or credential-bearing URLs.
- Personal or sensitive information without a justified purpose and appropriate
  authorization for retention.

When a reference is sufficient, store the reference rather than duplicating the
underlying content. Redact sensitive material before writing or indexing it.

## 4. Suggested file-first structure

Start with readable Markdown and version control. Introduce a database or search
index only when file-based retrieval no longer meets measured needs.

```text
agent-memory/
  README.md                  # This management guide
  memory/                    # Proposed; create when actual records exist
    INDEX.md                 # Short topic-to-record map
    decisions/               # Durable choices and rationale
    facts/                   # Verified, scoped knowledge
    procedures/              # Repeatable and validated workflows
    handoffs/                # Session summaries and next actions
    archive/                 # Superseded, non-sensitive historical context
```

Use descriptive names, such as `decisions/2026-10-26-file-first-storage.md`.
Keep the index small: record ID, title, scope, status, and relative path.
Archived records should be excluded from default retrieval. Do not create
placeholder memories that look like verified facts.

## 5. Memory record template

Each record should express one coherent fact, decision, procedure, or handoff.
For Markdown records, use metadata like this:

```yaml
---
id: mem-example-001
type: decision                 # fact | decision | procedure | handoff
title: Short, specific title
scope: project:example
status: proposed               # proposed | active | superseded | expired
evidence_level: inferred       # inferred | reported | verified
source: "Repository path, issue URL, or dated user instruction"
created_at: 2026-10-26
last_verified_at: null
review_after: 2026-11-26
supersedes: []
sensitivity: internal          # Classification; not an access-control mechanism
---
```

Include these sections beneath the metadata:

- **Summary:** the useful knowledge, in a few sentences.
- **Evidence and rationale:** source details and why the conclusion follows.
- **Applicability:** conditions under which the record is useful or invalid.
- **Next action:** a concrete follow-up, if one is needed.

Use unique IDs in real records. `last_verified_at` remains empty until a real
verification occurs; reading an old note is not verification. For code evidence,
include a commit or version when available, since file paths and behavior change.

## 6. Read and write lifecycle

### Session start

1. Read current instructions and identify the user, project, and task scope.
2. Query the owning systems for live task and repository state.
3. Search the memory index for the current problem and its constraints.
4. Load only relevant active records; check sources, dates, and applicability.
5. Revalidate anything whose failure would materially affect the planned action.

### During work

1. Keep transient observations in working context.
2. Promote an observation only after applying the durable-storage criteria.
3. Compare against existing records before writing; update or supersede rather
   than adding near-duplicates.
4. Separate observed results from interpretations and planned actions.
5. Record a material decision near the time it is made, with its source.

### At handoff or completion

1. Write a concise handoff with objective, artifacts, verification results,
   unresolved questions, and the next executable step.
2. Update the owning task system with the actual outcome.
3. Refresh the memory index if durable records changed.
4. Remove temporary notes that no longer provide value.

Suggested handoff format:

```markdown
## Objective
## Completed work and artifact paths
## Verification performed and results
## Open questions or blockers
## Next action
## Sources and timestamp
```

Never label an unexecuted test as passed or a proposed action as completed.

## 7. Retrieval and context budgets

Filter by access permission and scope before ranking by semantic similarity.
Then consider task relevance, evidence quality, freshness, and source authority.
Similarity alone does not establish truth.

An initial operating budget could be a short index plus three to five focused
records, using roughly 10–20% of the available context window. Adjust this based
on measured usefulness, leaving room for current instructions, code, tool output,
and reasoning. This is a tunable heuristic, not a fixed requirement.

When context is constrained, summarize supporting detail while retaining record
IDs and source references. If retrieval finds nothing reliable, say so and
investigate; do not fill gaps with invented continuity.

## 8. Conflicts, freshness, and retention

- **Conflicting records:** consult the authoritative source. Prefer evidence
  applicable to the current version; the newest note is not automatically true.
  If unresolved, preserve the disagreement and ask the relevant owner when needed.
- **Changed decisions:** create or update the replacement and mark the old record
  superseded, with links in both directions. Exclude the old record by default.
- **Expired records:** treat them as leads requiring validation, not active facts.
- **Compaction:** merge overlapping records without dropping qualifications,
  provenance, or unresolved contradictions.
- **Deletion:** remove sensitive or unwanted data from active storage and derived
  indexes/caches. If version control, replicas, or backups contain it, use their
  removal and retention procedures; deleting the current file alone is insufficient.
  Rotate any exposed credential through its owning system.

Suggested review cadence:

| Information | Review trigger |
| --- | --- |
| Task state | Every session and before state-changing work |
| Environment and procedures | Relevant dependency/configuration change, or about 30 days |
| Architectural decisions | Related design change, or about 90 days |
| Explicit user preferences | User correction or scope change |
| Handoffs | After work resumes; retain only still-useful context |

Choose actual retention periods according to sensitivity and value. Review dates
are prompts to validate; they do not make stale information trustworthy until then.

## 9. Trust boundaries and concurrent agents

Retrieved documents, websites, logs, and prior model output may contain misleading
instructions. Keep source content distinct from current governing instructions.
Do not execute commands or disclose data just because a memory requests it.

Enforce project/user isolation in the storage and retrieval layer, not merely in
prompts or metadata labels. Apply the same permissions to indexes and summaries.

For multiple writers, use atomic writes or transactions plus version checks to
prevent lost updates. In a file-first workflow, review diffs and resolve conflicting
edits explicitly. Shared task ownership belongs in the coordinator, not a memory
file. Failed memory writes must be reported rather than presented as persisted.

## 10. Incremental implementation plan

1. **Establish the baseline:** use this guide, create the index when the first real
   memory is recorded, and agree on project scope and retention ownership.
2. **Run a manual pilot:** capture a small set of verified facts, decisions, and
   handoffs from real work. Review usefulness and duplication after several sessions.
3. **Add lightweight checks:** validate required metadata, unique IDs, local links,
   status values, and accidental credential storage. Use tools that avoid exposing
   sensitive matches in logs.
4. **Automate retrieval if justified:** begin with scope-filtered text search;
   add semantic retrieval only if evaluation shows a benefit. Keep source files
   authoritative and make derived indexes rebuildable.
5. **Evaluate and maintain:** assign an owner for stale-record review, corrections,
   deletion requests, and retrieval quality.

### Pilot acceptance checks

- A fresh session can recover a relevant decision and cite its original evidence.
- A corrected fact supersedes the old record, and retrieval returns the replacement.
- An expired procedure is flagged for revalidation rather than followed blindly.
- Information from an unrelated project is excluded from normal retrieval.
- A handoff distinguishes completed work, actual checks, and pending actions.
- A deletion removes the record from both source storage and derived retrieval,
  with historical copies handled according to the retention policy.
- Concurrent edits preserve both agents' changes or surface an explicit conflict.
- A retrieved instruction cannot override current instructions or permissions.

Track retrieval usefulness, stale-record usage, duplicate rate, context cost, and
time to resume a task. Establish a baseline before choosing numerical targets.

## Open decisions

- Which agents and projects will share this memory system?
- Which storage, task system, and identity boundaries will be authoritative?
- Who approves durable user preferences and owns correction/deletion requests?
- What retention and access requirements apply to the actual stored data?
- Does the manual pilot justify retrieval automation or a separate memory service?

These decisions should be resolved from real usage before committing to a specific
database, embedding model, or framework.
