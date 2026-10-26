"""Report a completed pipeline outcome, not acceptance of an asynchronous deploy."""

import json
import os
import urllib.error
import urllib.request

from environment import SHA, validate_url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    base = validate_url(os.environ["COORDINATOR_URL"])
    key = os.environ["COORDINATOR_API_KEY"]
    sha = os.environ["RELEASE_SHA"]
    environment = os.environ["DEPLOY_ENVIRONMENT"]
    outcome = os.environ["DEPLOY_OUTCOME"]
    if not SHA.fullmatch(sha) or environment not in ("development", "production"):
        raise ValueError("Invalid deployment identity")
    run_url = os.environ["DEPLOY_RUN_URL"]

    def post(path, data):
        request = urllib.request.Request(base + path, data=json.dumps(data).encode(), headers={
            "Authorization": "Bearer " + key, "Content-Type": "application/json",
        })
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Coordinator report failed with HTTP {exc.code}; no unsafe retry") from None

    task = post("/api/tasks", {
        "title": f"Deploy agent-memory {sha[:12]} to {environment}", "project": "agent-memory",
        "description": f"Pipeline outcome for full release {sha}. Run: {run_url}", "priority": 10,
    })
    task_id = task["id"]
    post(f"/api/tasks/{task_id}/claim", {})
    if outcome == "success":
        result = {"status": "done", "result_summary": (
            f"Release {sha} shipped to {environment}; internal and ingress-authenticated MCP smoke "
            f"and runner health checks passed. Run: {run_url}"
        )}
    else:
        result = {"status": "blocked", "reason": (
            f"Deployment outcome {outcome}; inspect release/migration state before retry. Run: {run_url}"
        )}
    post(f"/api/tasks/{task_id}/status", result)
    print(f"Reported {outcome} deployment as coordinator task #{task_id}")


if __name__ == "__main__":
    main()
