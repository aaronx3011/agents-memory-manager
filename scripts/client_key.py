"""Issue a non-admin agent credential from an explicitly selected service."""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from environment import Target, add_target_arguments, private_write, validate_url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(base, token, path, data=None, method=None):
    request = urllib.request.Request(validate_url(base) + path, method=method,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Memory request failed with HTTP {exc.code}; no credentials logged") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_target_arguments(parser)
    parser.add_argument("path", type=Path, help="New private key file; parent must exist")
    parser.add_argument("--url", help="Explicit service origin; defaults to the selected environment")
    parser.add_argument("--name", default="OpenCode personal memory")
    args = parser.parse_args()
    if args.path.exists() or not args.path.parent.is_dir():
        parser.error("Key file must be new and its parent directory must exist")
    target = Target.from_args(args)
    result = request_json(args.url or target.default_url(), target.values["MEMORY_ADMIN_TOKEN"],
        "/api/credentials", {"name": args.name, "all_projects": True,
                             "allow_shared": True, "can_write": True})
    private_write(args.path, result["token"])
    print(f"Created agent credential {result['id']} in a private file; token not printed.")


if __name__ == "__main__":
    main()
