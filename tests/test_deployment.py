import io
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backup
import environment
import report_deployment


def provision(root, name="development", owner=None):
    folder = root / "deploy" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "compose.yaml").write_text("services: {}\n")
    values = {"POSTGRES_PASSWORD": "p" * 40, "MEMORY_DB_PASSWORD": "d" * 40,
              "MEMORY_ADMIN_TOKEN": "t" * 48, "MEMORY_OWNER_ID": str(owner or uuid4()),
              "PROXY_NETWORK": "fixture-proxy", "MEMORY_PUBLIC_HOST": "memory.example.test"}
    environment.private_write(folder / ".env", "".join(f"{k}={v}\n" for k, v in values.items()))
    return folder, values


def test_target_selects_explicit_config_and_overrides_ambient_secrets(tmp_path, monkeypatch):
    folder, values = provision(tmp_path)
    monkeypatch.setenv("MEMORY_DB_PASSWORD", "unrelated-local-password")
    target = environment.Target("development", project="agent-memory-verify-dev", image_tag="a" * 40, root=tmp_path)
    assert target.process_env["MEMORY_DB_PASSWORD"] == values["MEMORY_DB_PASSWORD"]
    assert target.command == ["docker", "compose", "--project-name", "agent-memory-verify-dev",
                              "--env-file", str(folder / ".env"), "--file", str(folder / "compose.yaml")]
    assert target.identity()["environment"] == "development"


def test_missing_private_config_or_release_never_falls_back_to_local(tmp_path):
    with pytest.raises(ValueError, match="Missing Compose"):
        environment.Target("production", image_tag="a" * 40, root=tmp_path)
    folder, _ = provision(tmp_path)
    with pytest.raises(ValueError, match="No selected release"):
        environment.Target("development", root=tmp_path)
    with pytest.raises(ValueError, match="commit SHA"):
        environment.Target("development", image_tag="latest", root=tmp_path)
    (folder / ".env").chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        environment.Target("development", image_tag="a" * 40, root=tmp_path)


def test_unverified_candidate_is_visible_to_operations(tmp_path):
    folder, _ = provision(tmp_path)
    environment.private_write(folder / ".release", "a" * 40)
    environment.private_write(folder / ".deploying", "b" * 40)
    assert environment.Target("development", root=tmp_path).image_tag == "b" * 40
    assert environment.Target("development", image_tag="c" * 40, root=tmp_path).image_tag == "c" * 40


def test_private_state_is_atomic_and_existing_identity_is_not_overwritten(tmp_path):
    path = tmp_path / "state"
    environment.private_write(path, "old")
    with pytest.raises(FileExistsError):
        environment.private_write(path, "unauthorized replacement")
    environment.private_write(path, "new", replace=True)
    assert path.read_text() == "new" and path.stat().st_mode & 0o077 == 0


def test_backup_refuses_wrong_owner_or_environment_before_accessing_database(tmp_path):
    _, values = provision(tmp_path, "production")
    target = environment.Target("production", image_tag="a" * 40, root=tmp_path)
    folder = tmp_path / "snapshot"
    folder.mkdir()
    manifest = {"target": {"environment": "development", "project": "agent-memory-dev",
                           "owner_id": str(uuid4())}}
    (folder / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="owner differs"):
        backup.restore(folder, "agent_memory_restore_fixture", target=target)
    manifest["target"]["owner_id"] = values["MEMORY_OWNER_ID"]
    (folder / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="cross-environment"):
        backup.restore(folder, "agent_memory_restore_fixture", target=target)


@pytest.mark.parametrize("url", ["https://user:key@example.test", "https://example.test/api",
                                  "https://example.test?key=secret", "file:///tmp/store"])
def test_service_origins_reject_credential_urls_and_route_overrides(url):
    with pytest.raises(ValueError):
        environment.validate_url(url)


@pytest.mark.parametrize("outcome,expected", [("success", "done"), ("failure", "blocked"),
                                             ("cancelled", "blocked")])
def test_pipeline_reports_actual_outcome_without_unsafe_mutation_retry(monkeypatch, outcome, expected):
    for key, value in {"COORDINATOR_URL": "https://coordinator.example.test",
                       "COORDINATOR_API_KEY": "fixture-key", "RELEASE_SHA": "a" * 40,
                       "DEPLOY_ENVIRONMENT": "production", "DEPLOY_OUTCOME": outcome,
                       "DEPLOY_RUN_URL": "https://github.com/example/repo/actions/runs/1"}.items():
        monkeypatch.setenv(key, value)
    requests = []

    class Opener:
        def open(self, request, timeout):
            requests.append((request.full_url, json.loads(request.data)))
            return io.StringIO('{"id":42}')

    monkeypatch.setattr(report_deployment.urllib.request, "build_opener", lambda *args: Opener())
    report_deployment.main()
    assert len(requests) == 3
    assert requests[0][1]["project"] == "agent-memory"
    assert requests[1][0].endswith("/42/claim")
    assert requests[-1][1]["status"] == expected
    assert "fixture-key" not in json.dumps(requests)
    if expected == "blocked":
        assert "reason" in requests[-1][1]


def test_production_compose_does_not_publish_database_or_app_ports():
    import yaml
    root = Path(__file__).resolve().parents[1]
    config = yaml.safe_load((root / "deploy/production/compose.yaml").read_text())
    assert all("ports" not in service for service in config["services"].values())
    assert "proxy" not in config["services"]["db"].get("networks", {})
    assert config["services"]["app"]["networks"]["proxy"]["aliases"] == ["agent-memory-prod-app"]
    assert "IMAGE_TAG:?" in config["services"]["db"]["image"]
    assert "IMAGE_TAG:?" in config["services"]["app"]["image"]
