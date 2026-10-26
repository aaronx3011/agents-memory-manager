# Deployment — Agent Task Manager delivery pattern

Repository: <https://github.com/aaronx3011/agents-memory-manager>

Local directory, coordinator project slug, Python package and image names remain
`agent-memory`. The repository name is `agents-memory-manager`.

## Current state

**The service is now deployed on the self-hosted worker machine `lesbian`
(10.8.0.6) and no longer runs on the Mac.**

| Item | Value |
| --- | --- |
| Host | `lesbian`, `10.8.0.6`, Debian 13, x86_64 |
| Path | `~/agent-memory` (`/opt` requires an unavailable sudo password) |
| Compose project | `agent-memory-dev` |
| Images | `agent-memory:7d10c17e668e1339134861e1175a33227ef045d1`, `agent-memory-db:7d10c17e…` |
| App URL (VPN) | `http://10.8.0.6:8765` — UI, `/docs`, `/mcp/` |
| App binding | Only `10.8.0.6:8765`; PostgreSQL is not published |
| Data | Migrated owner identity, 1 project, 1 source memory, 1 checkpoint |
| Hosted CI | Passed for `7d10c17` ([run](https://github.com/aaronx3011/agents-memory-manager/actions/runs/40378843294)) |
| Local Mac runtime | Containers, volumes, `.env` and backups removed |
| OpenCode | MCP and plugin repointed to `http://10.8.0.6:8765`; `opencode mcp list` connected |

The deployment used the committed scripts and SHA images manually on the host,
because GitHub Actions has no registered runner for this repository and
`DEPLOY_ENABLED` is not set. The `ship` job therefore remains disabled until the
runner and deployment inputs are configured. No HTTPS ingress is configured yet;
access is over the encrypted WireGuard VPN and bound to the VPN interface.

Initial publication and hosted CI verification are recorded in task #116. The
deployment assets themselves were delivered by task #115.

Implemented assets:

| Asset | Purpose |
| --- | --- |
| `.github/workflows/ci.yml` | Isolated real PostgreSQL/pgvector tests, lint, adapter, MCP and Chromium checks |
| `.github/workflows/deploy.yml` | SHA-gated CI, self-hosted runner build, SSH shipment, ingress checks, coordinator reporting |
| `deploy/development/compose.yaml` | SHA-tagged app/database images, explicit bind IP/port and dedicated volumes |
| `deploy/production/compose.yaml` | SHA-tagged images, no host ports, app-only external proxy network |
| `scripts/configure.py` | Explicit one-time environment provisioning without replacing existing identity |
| `scripts/deploy.sh`, `scripts/deploy.py` | Exact-image startup, pre-update backup, model warmup, authenticated MCP smoke, release state |
| `scripts/environment.py` | Shared explicit environment/Compose/project selection |
| `scripts/backup.py`, `scripts/verify_restore.py` | Environment-bound backup metadata, scratch restore, deletion replay and migration checks |
| `scripts/client_key.py` | Target-aware non-admin agent-key provisioning |
| `scripts/report_deployment.py` | Actual done/blocked pipeline outcome reporting to the coordinator |
| `scripts/verify_deployment.py` | Disposable local development/production deployment and recovery verification |

## Infrastructure reused from agents-task-manager

The coordinator's `.github/workflows/deploy.yml` documents a self-hosted runner
at `10.8.0.6`, labels `[self-hosted, dev-runner]`, image shipment using
`docker save | gzip | ssh ... docker load`. Memory is deployed on that same
worker machine (`10.8.0.6`); the coordinator's separate development host is `10.8.0.11`.
Its production template uses a separately configured target and external proxy
network, without a published web port. Its runner container uses host networking
for VPN reachability. Operations issue:
<https://github.com/aaronx3011/agents-task-manager/issues/3>.

`https://atm.aaron-henriquez.com` is documented as that project's public
**development** environment. Public reachability does not establish that the
coordinator's separate manual production template is already provisioned.

Memory follows this delivery machinery with its own directory, database, images,
credentials and volumes. It does not use the coordinator database, Redis, task
reaper or Django commands. The memory app remains its tested single-process
service with a durable PostgreSQL job worker.

```text
agents-memory-manager GitHub repository
  -> verify selected SHA on a GitHub-hosted disposable Docker stack
  -> [self-hosted, dev-runner] builds app + custom pgvector image for target CPU
  -> gzip/SSH image shipment; rsync versioned assets
  -> ~/agent-memory/deploy/{development,production}   # this host: sudo unavailable
  -> internal MCP verification + runner health + authenticated ingress MCP check
  -> coordinator deployment outcome
```

## 1. Provision repository runner access

The coordinator's repository-scoped runner is not automatically available to this
repository. Either grant an existing organization runner group access, or register
a separate runner using the coordinator's `deploy/runner` pattern. A second runner
needs its own name, persisted registration volume and work directory; retain the
coordinator runner's registration.

Use labels `self-hosted` and `dev-runner`. Confirm the runner reaches the target
over the VPN, has Docker/SSH/rsync/Python 3, and builds for the target architecture.
Do not ship a Mac ARM64 image to an unverified Linux target architecture.

## 2. Configure GitHub environments and deployment inputs

Create environments `development` and `production`. Set the production required
reviewer rule as in the coordinator's intended production process. Pushes to main
target development; production is manual dispatch of the selected ref/SHA.

Configure these **secrets** in the appropriate environment/repository:

| Secret | Use |
| --- | --- |
| `DEV_HOST`, `DEV_SSH_USER`, `DEV_SSH_KEY` | VPN development host, user and base64-encoded SSH private key |
| `PROD_HOST`, `PROD_SSH_USER`, `PROD_SSH_KEY` | Explicit production target and SSH identity |
| `DEPLOY_KNOWN_HOSTS` | Verified SSH known-hosts lines for the selected target |
| `COORDINATOR_URL`, `COORDINATOR_API_KEY` | Reporting under the registered `agent-memory` coordinator project |

Configure these **Actions variables**:

| Variable | Example/purpose |
| --- | --- |
| `DEPLOY_ENABLED` | Repository-level variable: set to `true` after runner/host/settings are ready; otherwise CI runs and shipping is skipped |
| `DEV_HEALTH_URL` | `http://10.8.0.6:8765/health` for the current worker deployment |
| `PROD_PUBLIC_HOST` | Dedicated memory HTTPS hostname, without scheme/path |

Secrets in `agents-task-manager` are not automatically available in this repo.
Provision approved access rather than copying raw secrets into source. The workflow
selects development/production inputs explicitly; missing production values do not
fall back to development. SSH host identity must match the supplied known-hosts file.

## 3. Prepare the target host and private environment

Use a separate `~/agent-memory` here (or `/opt/agent-memory` where sudo is available), owned by the deployment user. That user needs
Docker access. Keep `/opt/agents-task-manager` unchanged. Provisioning needs the
memory `deploy/` and `scripts/` directories on the host before the first deployment;
they can be transferred after publishing or securely copied from this checkout.

For development, select a free VPN-facing port and bind IP. Example on the existing
development target (confirm these values for the actual host):

```sh
python3 scripts/configure.py --environment development \
  --bind-ip 10.8.0.6 --port 8765
```

For production, first confirm the existing HTTPS proxy's Docker network and memory
hostname. Example placeholders:

```sh
python3 scripts/configure.py --environment production \
  --proxy-network EXISTING_PROXY_NETWORK \
  --public-host memory.example.com
```

These explicit provisioning commands generate private random credentials once in
`deploy/<environment>/.env` (0600), print no secrets and retain existing files.
Deployment itself never creates/replaces a missing environment. Preserve owner
identity and database passwords when using an existing volume.

Production Compose publishes neither app nor DB ports. The app joins the selected
external proxy network with alias `agent-memory-prod-app`, port 8765; the DB stays
on the stack-private network. Use the existing ingress/certificate management and
preserve Authorization/Streamable HTTP. The actual proxy product/network and DNS
remain infrastructure inputs; no new Caddy instance is required by this strategy.

For migration from the existing local store, preserve its `MEMORY_OWNER_ID`, owner
token and matching database configuration rather than generating a fresh identity.
See backup/migration selection below before opening writers on a restored store.

## 4. Publish and trigger the first development release

The local origin is `https://github.com/aaronx3011/agents-memory-manager.git`.
Publish the reviewed initial commit to `main` once explicitly authorized. Confirm
`.env`, environment files, token/key files, backup artifacts and runtime/release
state remain ignored. Initial publication is tracked in coordinator task #116.

The deployment workflow first calls the reusable CI workflow for the **same SHA**.
Only a successful verification job unlocks the self-hosted shipping job; unlike
independent push-triggered workflows, a failing CI run cannot race deployment.
PR/non-main checks run on GitHub-hosted runners, without deployment credentials.
Initial publication can therefore verify CI before a runner is provisioned: leave
the repository variable `DEPLOY_ENABLED` unset until deployment inputs are ready.

The shipping job:

1. Validates the checkout SHA and selected target, creates isolated temporary SSH files.
2. Builds `agent-memory:<SHA>` and `agent-memory-db:<SHA>` from pinned bases/locked deps.
3. Ships **both** images over SSH. The DB image includes role/pgvector initialization.
4. Rsyncs versioned deploy/scripts assets, excluding private configuration and markers.
5. Calls `bash ~/agent-memory/scripts/deploy.sh development <SHA>`.
6. Checks ingress health from the runner and authenticated MCP through that origin
   from the deployed app, keeping its owner credential private on the target.
7. Reports the actual outcome and GitHub run URL to the coordinator, then removes SSH files.

The target script requires full 40-character SHA tags and already-loaded images.
It performs startup migrations, bootstrap, embedding warmup and two-client MCP smoke.
Updates take an environment-specific backup of the previous verified release first.

## 5. Select the environment explicitly for operations

All examples below run from `~/agent-memory` on the worker. Helpers default to the root local
Compose setup for backwards compatibility. **Always pass `--environment` on a server.**

```sh
python3 scripts/environment.py --environment development -- ps
python3 scripts/environment.py --environment production -- logs --tail 100 app
python3 scripts/environment.py --environment production -- exec -T app agent-memory status
python3 scripts/environment.py --environment production -- exec -T app agent-memory token
```

Helpers read the selected private environment and pass explicit Compose file,
project name and env-file arguments. They do not inherit unrelated local database
credentials. Image selection comes from that environment's release markers; for
first-start/offline operations, pass `--image-tag <FULL_SHA>`.

`.release` records the last internally verified SHA; `.previous-release` records
its predecessor. `.deploying` records an attempted, unverified release and is kept
on failure. Operations see that candidate rather than quietly targeting an older
image. Inspect migration/runtime state before reconciling a failed candidate;
there is no automatic schema rollback or destructive volume cleanup.

Register this project's client-directory aliases explicitly, preserving existing ones:

```sh
python3 scripts/environment.py --environment production -- exec -T app \
  agent-memory bootstrap --directory /absolute/client/path/to/agent-memory \
  --repository https://github.com/aaronx3011/agents-memory-manager.git
```

The path is the OpenCode client's project directory, not the server checkout.
Register other projects with their names/repository/directory aliases in the UI.

## 6. Back up, restore and migrate the selected store

```sh
python3 scripts/backup.py --environment production backup
python3 scripts/backup.py --environment production verify backups/production/agent-memory-prod/<timestamp>
python3 scripts/verify_restore.py --environment production
```

Paths are `backups/<environment>/<compose-project>/<timestamp>`. The default
production Compose project is `agent-memory-prod`; development is `agent-memory-dev`.
An explicit `--project` selects a separate named stack. Use the exact path printed
by the backup command. Manifests identify owner,
environment and project as well as dump checksum. Scratch restores reject mismatched
owners and require explicit `--allow-cross-environment` for deliberate migration.

To migrate a local snapshot to production, provision the preserved owner identity,
supply `--environment production --allow-cross-environment`, and provide a current
`--ledger FILE` if the source DB is unavailable. The restore helper accepts only a
new `agent_memory_restore_*` database; promotion into the canonical `agent_memory`
database remains an explicit maintenance step with writers stopped. Verify before
promotion; do not point the app at a renamed database while backups still target
the canonical name.

Keep encrypted scheduled off-host backups, a current independent deletion ledger
and tested recovery. Backup/ledger scheduling, encryption destination and production
monitoring are infrastructure configuration, not silently installed by these files.
Off-host ledger replication before purge acknowledgement remains a stricter future
durability capability; periodic export has a known gap between exports.

## 7. Connect OpenCode and promote production

After verified development deployment, manually dispatch `Deploy memory` for
`production` on the chosen tested ref. GitHub environment protection controls the
production job. Confirm public HTTPS, authenticated MCP, project isolation,
correction/checkpoint behavior, restart persistence and recovery before normal use.

Provision a non-admin memory key from the selected server:

```sh
python3 scripts/client_key.py --environment production /private/new-memory-agent-key
```

The production helper uses `MEMORY_PUBLIC_HOST`; `--url https://...` can explicitly
select the origin. Copy the private agent key to the client machine and update:

```text
OpenCode MCP URL:      https://<MEMORY_PUBLIC_HOST>/mcp/
Plugin service URL:   https://<MEMORY_PUBLIC_HOST>
Token file:           private production memory agent key, not the coordinator key
```

Quit/restart OpenCode, run `opencode mcp list`, and verify recall in a fresh
conversation. The task-coordinator connection and worker bridge remain separate.

## Verification and rollout boundaries

Local verification uses synthetic SHA aliases and distinct disposable stacks;
it does not claim a real GitHub release or remote TLS/VPN deployment:

```sh
docker compose build app db
python3 scripts/verify_deployment.py
python3 scripts/verify_deployment.py --only development --browser
```

The harness checks new deployment, pre-update backup, second-release update,
scratch restore/deletion replay, authenticated MCP, restart persistence, no DB host
port, production app-only proxy membership and no production app host port. Browser
mode checks the actual owner workflow on a random non-default development port.
Only its own test networks/volumes/image aliases are removed.

Remote prerequisites remaining: initial publication, repository runner access,
GitHub environments/SSH/reporting inputs, host-private configuration, existing
proxy/DNS values, backup destination/schedule and the actual rollout. See
`VERIFICATION.md` for executed results rather than treating these prerequisites as done.
