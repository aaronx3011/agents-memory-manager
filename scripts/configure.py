"""Explicit one-time provisioning; never replace an existing environment identity."""

import argparse
import secrets
import uuid
from pathlib import Path

from environment import ENVIRONMENTS, ROOT, private_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=ENVIRONMENTS, default="local")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--bind-ip", default="127.0.0.1")
    parser.add_argument("--proxy-network")
    parser.add_argument("--public-host")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Invalid port")
    directory = ROOT if args.environment == "local" else ROOT / "deploy" / args.environment
    path = args.env_file or directory / ".env"
    if not path.parent.is_dir():
        parser.error("Environment parent directory must already exist")
    if path.exists():
        print("Existing environment retained; no credential or identity was changed.")
        return
    if args.environment == "production" and not (args.proxy_network and args.public_host):
        parser.error("Production provisioning requires --proxy-network and --public-host")
    from ipaddress import ip_address
    ip_address(args.bind_ip)
    if args.public_host and any(x not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for x in args.public_host):
        parser.error("Public host must be a hostname, not a URL")
    if args.proxy_network and any(x not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for x in args.proxy_network):
        parser.error("Invalid proxy network name")
    content = (
        f"POSTGRES_PASSWORD={secrets.token_hex(32)}\n"
        f"MEMORY_DB_PASSWORD={secrets.token_hex(32)}\n"
        f"MEMORY_ADMIN_TOKEN={secrets.token_urlsafe(48)}\n"
        f"MEMORY_OWNER_ID={uuid.uuid4()}\n"
        f"MEMORY_PORT={args.port}\nMEMORY_BIND_IP={args.bind_ip}\n"
    )
    if args.proxy_network:
        content += f"PROXY_NETWORK={args.proxy_network}\n"
    if args.public_host:
        content += f"MEMORY_PUBLIC_HOST={args.public_host}\n"
    private_write(path, content)
    print(f"Created private {args.environment} configuration; no secrets printed.")


if __name__ == "__main__":
    main()
