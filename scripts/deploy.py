"""Deploy loaded, SHA-tagged images without building or deleting persistent volumes."""

import argparse
import fcntl
import os
import subprocess

import backup
from environment import SHA, Target, private_write


def deploy(target, *, skip_backup=False):
    if target.environment == "local":
        raise ValueError("Use root Compose for local development")
    tag = target.image_tag
    for image in (f"agent-memory:{tag}", f"agent-memory-db:{tag}"):
        subprocess.run(["docker", "image", "inspect", image], check=True, stdout=subprocess.DEVNULL)
    if target.environment == "production":
        subprocess.run(["docker", "network", "inspect", target.values["PROXY_NETWORK"]],
                       check=True, stdout=subprocess.DEVNULL)
    if target.candidate_file.exists() and target.candidate_file.read_text().strip() != tag:
        raise ValueError("Another unverified release exists; inspect/reconcile .deploying before changing it")
    previous = target.release_file.read_text().strip() if target.release_file.exists() else None
    if skip_backup and target.environment == "production":
        raise ValueError("Production deployments cannot skip the pre-update backup")
    if previous and not skip_backup:
        old = Target(target.environment, target.env_file, target.project, previous, target.root)
        backup.backup(target=old)
    private_write(target.candidate_file, tag, replace=True)
    try:
        target.run("up", "-d", "--wait", "--wait-timeout", "600", "--no-build")
        target.run("exec", "-T", "app", "agent-memory", "bootstrap",
                   "--repository", "https://github.com/aaronx3011/agents-memory-manager.git")
        target.run("exec", "-T", "app", "agent-memory", "warmup")
        target.run("exec", "-T", "app", "python", "-c",
                   "import urllib.request; urllib.request.urlopen('http://localhost:8765/health',timeout=5)")
        target.run("exec", "-T", "-e", "MEMORY_URL=http://127.0.0.1:8765",
                   "app", "python", "scripts/mcp_smoke.py")
    except BaseException:
        print("Release not verified. .deploying records the attempted SHA; inspect migrations and "
              "the pre-update backup before retrying or rolling back. No success marker written.")
        raise
    if previous:
        private_write(target.directory / ".previous-release", previous, replace=True)
    private_write(target.release_file, tag, replace=True)
    target.candidate_file.unlink()
    print(f"Verified {target.environment} release {tag}; volumes retained.")
    target.run("ps")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=["development", "production"])
    parser.add_argument("sha")
    parser.add_argument("--env-file")
    parser.add_argument("--project")
    parser.add_argument("--skip-backup", action="store_true", help="Disposable development only")
    args = parser.parse_args()
    if not SHA.fullmatch(args.sha):
        parser.error("A full commit SHA is required")
    target = Target(args.environment, args.env_file, args.project, args.sha)
    fd = os.open(target.directory / ".deploy.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deploy(target, skip_backup=args.skip_backup)
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
