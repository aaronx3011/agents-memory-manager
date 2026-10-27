# Project administration

Connect to the dashboard with the owner credential and select **Manage projects**.
The panel lists registered projects, repository URLs, and directory aliases.

- **Register project** creates a centrally registered identity.
- **Edit** updates the name, optional repository URL, and directory aliases (one
  per line, up to 30). Saving replaces the alias list; remove obsolete paths or add
  corrected paths here. The project UUID and its stored data remain the same.
- **Remove** asks for confirmation and removes an empty project and its grants
  from scoped access keys. Projects containing any memories, checkpoints, or jobs
  return a conflict and remain registered. This operation does not cascade-delete
  stored knowledge or move it into owner-wide memory.

Project names and identities are trimmed; aliases are deduplicated. Duplicate
names return a conflict, and failed saves retain the form for correction.
Administrative actions are audited. Scoped agent credentials cannot create,
update, or remove projects, even when granted write access to all projects.

## HTTP endpoints

All endpoints require a Bearer credential. Project writes require the owner.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/session` | Returns `can_manage` for dashboard controls |
| `GET /api/projects` | Lists projects permitted by the credential |
| `POST /api/projects` | Creates a project; returns 201 |
| `PUT /api/projects/{uuid}` | Replaces name, repository URL, and aliases |
| `DELETE /api/projects/{uuid}` | Removes an empty project; returns 409 if occupied |

Create and update accept `{ "name": "example", "repo_url": null, "aliases": [] }`.
Unknown or other-owner project IDs return 404. Owner isolation applies to all
queries and mutations. Project deletion locks the row before checking dependent
records and removing credential grants, in the same transaction.

Verification is included in `tests/test_projects.py` and
`tests/browser/workspace.spec.js`, executed by the existing CI workflow against
real PostgreSQL/pgvector and Chromium.
