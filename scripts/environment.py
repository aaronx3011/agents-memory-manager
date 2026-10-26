"""Explicit, shared Compose/environment selection for every host-side operation."""

import argparse
import json
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENTS = ("local", "development", "production")
SHA = re.compile(r"[a-f0-9]{40}")


def read_env(path):
    values = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ValueError(f"Invalid environment assignment on line {number}")
        parts = shlex.split(value, comments=True)
        if len(parts) > 1 or key in values:
            raise ValueError(f"Invalid or repeated environment field on line {number}")
        values[key] = parts[0] if parts else ""
    return values


def private_write(path, text, replace=False):
    """Private atomic operational state; never partially publish a release marker."""
    path = Path(path)
    if not replace:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        return
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".memory-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Target:
    def __init__(self, environment="local", env_file=None, project=None, image_tag=None, root=None):
        if environment not in ENVIRONMENTS:
            raise ValueError("Unknown environment")
        self.environment = environment
        self.root = Path(root or ROOT).resolve()
        self.directory = self.root if environment == "local" else self.root / "deploy" / environment
        self.compose_file = self.directory / "compose.yaml"
        self.env_file = Path(env_file).resolve() if env_file else self.directory / ".env"
        if not self.compose_file.is_file() or not self.env_file.is_file():
            raise ValueError(f"Missing Compose/configuration for {environment}; provision it explicitly")
        if self.env_file.stat().st_mode & 0o077:
            raise ValueError("Environment file must be private (chmod 600)")
        self.values = read_env(self.env_file)
        self.project = project or {"local": "agent-memory", "development": "agent-memory-dev",
                                   "production": "agent-memory-prod"}[environment]
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,90}", self.project):
            raise ValueError("Invalid Compose project name")
        self.release_file = self.directory / ".release"
        self.candidate_file = self.directory / ".deploying"
        self.image_tag = image_tag
        if not self.image_tag:
            for marker in (self.candidate_file, self.release_file):
                if marker.is_file():
                    self.image_tag = marker.read_text().strip()
                    break
        if environment != "local" and not self.image_tag:
            raise ValueError("No selected release; pass --image-tag with a full commit SHA")
        if self.image_tag and not SHA.fullmatch(self.image_tag):
            raise ValueError("Image tag must be a full 40-character lowercase commit SHA")
        for key in ("POSTGRES_PASSWORD", "MEMORY_DB_PASSWORD", "MEMORY_ADMIN_TOKEN", "MEMORY_OWNER_ID"):
            if not self.values.get(key):
                raise ValueError(f"Missing required setting: {key}")
        from uuid import UUID
        UUID(self.values["MEMORY_OWNER_ID"])
        if len(self.values["MEMORY_ADMIN_TOKEN"]) < 32:
            raise ValueError("Owner token is too short")
        for key in ("POSTGRES_PASSWORD", "MEMORY_DB_PASSWORD"):
            if not re.fullmatch(r"[A-Za-z0-9_-]{24,}", self.values[key]):
                raise ValueError(f"{key} must be URL-safe with at least 24 characters")
        if environment == "production" and not self.values.get("PROXY_NETWORK"):
            raise ValueError("Production requires the existing external PROXY_NETWORK")

    @classmethod
    def from_args(cls, args):
        return cls(args.environment, args.env_file, args.project, args.image_tag)

    @property
    def process_env(self):
        # Ambient local database/owner settings must never override a selected target.
        env = os.environ.copy()
        for key in ("POSTGRES_PASSWORD", "MEMORY_DB_PASSWORD", "MEMORY_ADMIN_TOKEN", "MEMORY_OWNER_ID",
                    "MEMORY_PORT", "MEMORY_BIND_IP", "PROXY_NETWORK", "IMAGE_TAG",
                    "EXTRACTION_BASE_URL", "EXTRACTION_API_KEY", "EXTRACTION_MODEL"):
            env.pop(key, None)
        env.update(self.values)
        if self.image_tag:
            env["IMAGE_TAG"] = self.image_tag
        return env

    @property
    def command(self):
        return ["docker", "compose", "--project-name", self.project, "--env-file", str(self.env_file),
                "--file", str(self.compose_file)]

    def run(self, *args, **kwargs):
        return subprocess.run(self.command + list(args), cwd=self.root, env=self.process_env,
                              check=True, **kwargs)

    def default_url(self):
        if self.environment == "production":
            host = self.values.get("MEMORY_PUBLIC_HOST")
            if not host or "/" in host or not re.fullmatch(r"[A-Za-z0-9.-]+", host):
                raise ValueError("Set MEMORY_PUBLIC_HOST or supply an explicit --url")
            return "https://" + host
        host = self.values.get("MEMORY_BIND_IP", "127.0.0.1")
        if host == "0.0.0.0":
            host = "127.0.0.1"
        return f"http://{host}:{self.values.get('MEMORY_PORT', '8765')}"

    def identity(self):
        return {"environment": self.environment, "project": self.project,
                "owner_id": self.values["MEMORY_OWNER_ID"]}


def add_target_arguments(parser):
    parser.add_argument("--environment", choices=ENVIRONMENTS, default="local")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--project", help="Explicit Compose project (use isolated names for verification)")
    parser.add_argument("--image-tag", help="Full commit SHA; defaults to deployed release marker")


def validate_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTP(S) service origin without embedded credentials")
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Use a service origin, without a path, query or fragment")
    return url.rstrip("/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_target_arguments(parser)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    target = Target.from_args(args)
    commands = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    if not commands:
        print(json.dumps({**target.identity(), "image_tag": target.image_tag,
                          "compose_file": str(target.compose_file)}))
    else:
        target.run(*commands)


if __name__ == "__main__":
    main()
