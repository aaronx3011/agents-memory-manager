"""Exercise SHA deployments/backups in disposable local development and production stacks.

Uses synthetic SHA image aliases and a disposable proxy network. Never contacts a
remote host or selects the actual local/deployed project's database or volumes.
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

import backup
import deploy
from environment import ROOT, Target, private_write

SHA_A, SHA_B = "0" * 39 + "1", "0" * 39 + "2"


def docker(*args):
    return subprocess.run(["docker", *args], check=True, stdout=subprocess.PIPE).stdout.decode()


def run_json(target, code):
    setup = (
        "import os,json,httpx; "
        "c=httpx.Client(base_url='http://localhost:8765',timeout=60,"
        "headers={'Authorization':'Bearer '+os.environ['MEMORY_ADMIN_TOKEN']}); "
    )
    output = target.run("exec", "-T", "app", "python", "-c", setup + code,
                        stdout=subprocess.PIPE).stdout.decode()
    return json.loads(output)


def main():
    import secrets
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["development", "production"])
    parser.add_argument("--browser", action="store_true", help="Run Chromium on the disposable development port")
    args = parser.parse_args()
    work = ROOT / ".verification"
    work.mkdir(exist_ok=True, mode=0o700)
    suffix = uuid4().hex[:10]
    proxy = f"agent-memory-verify-proxy-{suffix}"
    aliases = []
    targets = []
    temporary = None
    docker("network", "create", proxy)
    try:
        for sha in (SHA_A, SHA_B):
            for source, name in (("agent-memory-app", "agent-memory"),
                                 ("agent-memory-db", "agent-memory-db")):
                alias = f"{name}:{sha}"
                docker("image", "tag", source, alias)
                aliases.append(alias)
        temporary = tempfile.TemporaryDirectory(prefix="deploy-", dir=work)
        root = Path(temporary.name)
        for name in ([args.only] if args.only else ("development", "production")):
            folder = root / "deploy" / name
            folder.mkdir(parents=True)
            shutil.copyfile(ROOT / "deploy" / name / "compose.yaml", folder / "compose.yaml")
            with socket.socket() as port:
                port.bind(("127.0.0.1", 0))
                number = port.getsockname()[1]
            values = {
                "POSTGRES_PASSWORD": secrets.token_hex(24), "MEMORY_DB_PASSWORD": secrets.token_hex(24),
                "MEMORY_ADMIN_TOKEN": secrets.token_urlsafe(40), "MEMORY_OWNER_ID": str(uuid4()),
                "MEMORY_PORT": number, "MEMORY_BIND_IP": "127.0.0.1",
                "PROXY_NETWORK": proxy, "MEMORY_PUBLIC_HOST": "memory.example.test",
            }
            private_write(folder / ".env", "".join(f"{k}={v}\n" for k, v in values.items()))
            project = f"agent-memory-verify-{name}-{suffix}"
            target = Target(name, project=project, image_tag=SHA_A, root=root)
            targets.append(target)
            deploy.deploy(target)
            before = run_json(target, "print(json.dumps(c.get('/api/projects').json()))")
            assert len(before) == 1
            if args.browser and name == "development":
                subprocess.run(["npm", "--prefix", str(ROOT / "tests/browser"), "test"], check=True,
                    env={**os.environ, "MEMORY_URL": target.default_url(),
                         "MEMORY_ENV_FILE": str(target.env_file)})
            app_id = target.run("ps", "-q", "app", stdout=subprocess.PIPE).stdout.decode().strip()
            db_id = target.run("ps", "-q", "db", stdout=subprocess.PIPE).stdout.decode().strip()
            inspected = json.loads(docker("inspect", app_id, db_id))
            assert not inspected[1]["HostConfig"]["PortBindings"]
            if name == "production":
                assert not inspected[0]["HostConfig"]["PortBindings"]
                assert proxy not in inspected[1]["NetworkSettings"]["Networks"]
                assert proxy in inspected[0]["NetworkSettings"]["Networks"]
            snapshot = backup.backup(target)
            assert json.loads((snapshot / "manifest.json").read_text())["target"] == target.identity()
            backup.restore(snapshot, f"agent_memory_restore_{suffix}", verify=True, target=target)
            updated = Target(name, project=project, image_tag=SHA_B, root=root)
            deploy.deploy(updated)  # Includes an automatic backup of the previously verified release.
            assert updated.release_file.read_text() == SHA_B
            assert (folder / ".previous-release").read_text() == SHA_A
            assert not updated.candidate_file.exists()
            updated.run("restart", "db", "app")
            updated.run("up", "-d", "--wait", "--wait-timeout", "180")
            after = run_json(updated, "print(json.dumps(c.get('/api/projects').json()))")
            assert after == before
            print(f"PASS {name}: deploy/update/backup/restore/restart/isolation ({project})")
            target.run("down", "--volumes", "--remove-orphans")
            targets.remove(target)
        print(f"Disposable {args.only or 'development and production'} deployment verification passed.")
    finally:
        for target in targets:
            try:
                target.run("down", "--volumes", "--remove-orphans")
            except subprocess.CalledProcessError:
                print(f"Cleanup required for disposable project {target.project}")
        docker("network", "rm", proxy)
        for alias in aliases:
            subprocess.run(["docker", "image", "rm", alias], check=False, stdout=subprocess.DEVNULL)
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    main()
