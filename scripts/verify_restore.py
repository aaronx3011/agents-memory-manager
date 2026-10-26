"""Prove that deletion after a backup survives restore in the selected environment."""

import argparse
from uuid import UUID, uuid4

import backup
from client_key import request_json
from environment import Target, add_target_arguments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_target_arguments(parser)
    parser.add_argument("--url")
    args = parser.parse_args()
    target = Target.from_args(args)
    base = args.url or target.default_url()

    def api(path, data=None, method=None):
        return request_json(base, target.values["MEMORY_ADMIN_TOKEN"], path, data, method)

    project = api("/api/projects/resolve?identity=agent-memory")
    memory = api("/api/memories", {
        "project_id": project["id"], "type": "episodic", "title": "Restore deletion fixture",
        "content": "This synthetic record must not reappear when restoring an older backup.",
        "sources": [{"kind": "test", "reference": "scripts/verify_restore.py"}],
        "idempotency_key": str(uuid4()),
    })
    deleted = False
    database = f"agent_memory_restore_{uuid4().hex[:12]}"
    restored = False
    try:
        folder = backup.backup(target)
        api("/api/memories/" + memory["id"], method="DELETE")
        deleted = True
        backup.restore(folder, database, target=target)
        restored = True
        count = backup.sql(f"SELECT count(*) FROM memories WHERE id='{UUID(memory['id'])}';",
                           database, target=target)
        assert count == "0", "Deleted fixture was resurrected"
        assert int(backup.sql("SELECT count(*) FROM memories;", database, target=target)) >= 1
        print("Older-backup deletion replay passed; working database retained, scratch database removed.")
    finally:
        if not deleted:
            api("/api/memories/" + memory["id"], method="DELETE")
        if restored:
            backup.docker("dropdb", "-U", "postgres", database, target=target)


if __name__ == "__main__":
    main()
