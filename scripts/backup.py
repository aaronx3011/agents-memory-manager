"""Local Docker backup and non-destructive restore drills (stdlib only).

Backups contain private memory and hashed credentials. Keep this ignored directory
private. The local MVP deliberately restores only to a new scratch database.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from environment import Target, add_target_arguments


def docker(*args, input=None, stdout=subprocess.PIPE, target=None):
    target = target or Target()
    return target.run("exec", "-T", "db", *args, input=input, stdout=stdout).stdout


def sql(query, database="agent_memory", target=None):
    return docker("psql", "-XAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", database,
                  input=query.encode(), target=target).decode().strip()


def current_ledger(target=None):
    return json.loads(sql(
        "SELECT coalesce(json_agg(t),'[]'::json) FROM "
        "(SELECT memory_id,owner_id,project_id,deleted_at FROM tombstones) t;", target=target,
    ))


def private_write(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(data, indent=2))
        stream.flush()
        os.fsync(stream.fileno())


def backup(target=None):
    target = target or Target()
    base = target.root / "backups" / target.environment / target.project
    folder = base / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True, mode=0o700)
    path = folder / "memory.dump"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        docker("pg_dump", "-U", "postgres", "-d", "agent_memory", "-Fc", stdout=stream, target=target)
        stream.flush()
        os.fsync(stream.fileno())
    private_write(folder / "deletions.json", current_ledger(target))
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    private_write(folder / "manifest.json", {
        "format": 2, "target": target.identity(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sha256": checksum,
    })
    print(f"Backup created: {folder.relative_to(target.root)}")
    return folder


def replay(ledger, database, target=None):
    # All values originate from UUID-validated ledger entries, never raw SQL input.
    from uuid import UUID
    ids = sorted({str(UUID(item["memory_id"])) for item in ledger})
    if not ids:
        return
    literals = ",".join(f"'{item}'::uuid" for item in ids)
    inserts = []
    for item in ledger:
        mid, owner = str(UUID(item["memory_id"])), str(UUID(item["owner_id"]))
        project = f"'{UUID(item['project_id'])}'::uuid" if item["project_id"] else "NULL"
        inserts.append(
            "INSERT INTO tombstones(memory_id,owner_id,project_id) "
            f"VALUES ('{mid}','{owner}',{project}) ON CONFLICT DO NOTHING;",
        )
    sql("BEGIN;" + "".join(inserts) + f"""
        DELETE FROM checkpoints WHERE memory_ids && ARRAY[{literals}];
        UPDATE captures SET memory_id=NULL WHERE memory_id IN ({literals});
        UPDATE memories SET supersedes=NULL WHERE supersedes IN ({literals});
        DELETE FROM memories WHERE id IN ({literals});
        COMMIT;
    """, database, target=target)


def restore(folder, database, ledger_path=None, verify=False, target=None, allow_cross_environment=False):
    target = target or Target()
    if not re.fullmatch(r"agent_memory_restore_[a-z0-9_]+", database):
        raise ValueError("Restore destination must be a new agent_memory_restore_* database")
    folder = folder.resolve()
    manifest = json.loads((folder / "manifest.json").read_text())
    origin = manifest.get("target")
    if origin:
        if origin["owner_id"] != target.values["MEMORY_OWNER_ID"]:
            raise ValueError("Backup owner differs from target; provision the preserved owner identity first")
        if origin != target.identity() and not allow_cross_environment:
            raise ValueError("Backup target differs; cross-environment migration requires --allow-cross-environment")
    elif target.environment != "local" and not allow_cross_environment:
        raise ValueError("Legacy backup has no target metadata; require explicit --allow-cross-environment")
    with (folder / "memory.dump").open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum != manifest["sha256"]:
        raise ValueError("Backup checksum mismatch")
    ledger = json.loads((folder / "deletions.json").read_text())
    # Obtain subsequent deletions before restoring an older snapshot. If the live
    # host is lost, supply its separately preserved latest ledger with --ledger.
    ledger += json.loads(ledger_path.read_text()) if ledger_path else current_ledger(target)
    started = time.monotonic()
    docker("createdb", "-U", "postgres", database, target=target)
    try:
        with (folder / "memory.dump").open("rb") as stream:
            target.run("exec", "-T", "db", "pg_restore", "-U", "postgres",
                       "--exit-on-error", "-d", database, stdin=stream)
        replay(ledger, database, target)
        remaining = int(sql(
            "SELECT count(*) FROM memories JOIN tombstones ON memories.id=tombstones.memory_id;",
            database, target=target,
        ))
        if remaining:
            raise RuntimeError("Deletion replay verification failed")
        stats = json.loads(sql(
            "SELECT json_build_object('projects',(SELECT count(*) FROM projects),"
            "'memories',(SELECT count(*) FROM memories),'checkpoints',(SELECT count(*) FROM checkpoints));",
            database, target=target,
        ))
        print(json.dumps({"database": database, "restored": True, "deletion_replay": "passed",
                          "seconds": round(time.monotonic() - started, 2), **stats}))
    finally:
        if verify:
            docker("dropdb", "-U", "postgres", database, target=target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_target_arguments(parser)
    parser.add_argument("command", choices=["backup", "verify", "restore", "ledger"])
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument("--database")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--allow-cross-environment", action="store_true")
    args = parser.parse_args()
    target = Target.from_args(args)
    if args.command == "backup":
        backup(target)
    elif args.command == "ledger":
        if not args.folder:
            parser.error("ledger requires a new output filename")
        private_write(args.folder, current_ledger(target))
        print("Content-free deletion ledger exported")
    else:
        if not args.folder:
            parser.error("restore/verify requires a backup folder")
        database = args.database or f"agent_memory_restore_{uuid4().hex[:12]}"
        restore(args.folder, database, args.ledger, args.command == "verify", target,
                args.allow_cross_environment)


if __name__ == "__main__":
    main()
