"""Hosted preflight must reject floating code and the foundation smoke graph."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/digitalocean/preflight.py"
TEMPLATE = SCRIPT.parent / "langgraph-agent.template.json"
spec = importlib.util.spec_from_file_location("hosted_preflight", SCRIPT)
assert spec is not None and spec.loader is not None
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def environment() -> dict[str, str]:
    return {
        **{name: "reviewed-nonsecret" for name in preflight.NONSECRET_VARS},
        **{name: "test-secret" for name in preflight.SECRET_VARS},
    }


def test_spec_renders_exact_sha_without_copying_secrets_into_env() -> None:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    rendered = preflight.render_spec(template, "a" * 40, environment())
    assert rendered["env"]["FRAMEWORK_REPO_SHA"] == "a" * 40
    assert rendered["env"]["ATLAS_DISCOVERY_PROFILE"] == "HOSTED_MANUAL"
    assert rendered["secrets"]["GITHUB_TOKEN"] == "oauth/github"
    assert "test-secret" not in json.dumps(rendered)
    assert all("TOKEN" not in name and "PAT" not in name for name in rendered["env"])


@pytest.mark.parametrize("sha", ["main", "a" * 39, "g" * 40])
def test_floating_or_invalid_sha_is_rejected(sha: str) -> None:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    with pytest.raises(preflight.PreflightError, match="exact 40-character"):
        preflight.render_spec(template, sha, environment())


def test_secret_like_env_field_fails_closed() -> None:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    template["env"]["UNREVIEWED_TOKEN"] = "test-secret"
    with pytest.raises(preflight.PreflightError, match="credential-like"):
        preflight.render_spec(template, "a" * 40, environment())


def test_smoke_graph_does_not_satisfy_sequential_node_set() -> None:
    with pytest.raises(preflight.PreflightError, match="smoke or incomplete graph"):
        preflight.validate_graph_nodes({"__start__", "fixture_smoke", "__end__"})


@pytest.mark.parametrize(
    "missing", ["generate_recommendation_rationale", "propose_search_expansions"]
)
def test_preflight_requires_every_reviewed_candidate_node(missing: str) -> None:
    with pytest.raises(preflight.PreflightError, match="smoke or incomplete graph"):
        preflight.validate_graph_nodes(preflight.REQUIRED_NODES - {missing})


def test_manifest_exports_real_sequential_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_hosted_graph import environment as hosted_environment

    for name, value in hosted_environment().items():
        monkeypatch.setenv(name, value)
    preflight.verify_sequential_graph()


def test_old_cli_version_syntax_is_recorded_without_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    def command(*args: str, timeout: int = 30) -> str:
        assert timeout == 30
        if args == ("doctl", "--version"):
            raise preflight.PreflightError("unknown flag")
        assert args == ("doctl", "version")
        return "doctl version 1.160.1-release\nrelease available"

    monkeypatch.setattr(preflight, "_command", command)
    assert preflight.installed_doctl_version() == "1.160.1-release"


def test_explicit_upgraded_doctl_path_overrides_shadowed_binary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    binary = tmp_path / "doctl.exe"
    binary.write_bytes(b"fixture")
    monkeypatch.setenv("ATLAS_DOCTL_BIN", str(binary))
    calls: list[tuple[str, ...]] = []

    def run(args: tuple[str, ...], **_kwargs: object) -> SimpleNamespace:
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout="doctl version 1.175.0-release")

    monkeypatch.setattr(preflight.subprocess, "run", run)
    assert preflight.installed_doctl_version() == "1.175.0-release"
    assert calls == [(str(binary), "--version")]


def test_preflight_uses_only_validation_and_dry_run_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sha = "a" * 40
    account_uuid = "11111111-2222-3333-4444-555555555555"
    calls: list[tuple[str, ...]] = []

    def command(*args: str, timeout: int = 30) -> str:
        assert timeout == 30
        calls.append(args)
        if args[:3] == ("doctl", "account", "get"):
            return account_uuid
        if args == ("git", "rev-parse", "HEAD"):
            return sha
        if args == ("git", "status", "--porcelain"):
            return ""
        if args[:2] == ("gh", "api"):
            return sha
        if args[:3] == ("doctl", "harness-runtime", "validate") and "--spec" in args:
            rendered = json.loads(Path(args[-1]).read_text(encoding="utf-8"))
            assert rendered["env"]["FRAMEWORK_REPO_SHA"] == sha
        return ""

    for name, value in environment().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(preflight, "_command", command)
    monkeypatch.setattr(preflight, "installed_doctl_version", lambda: "reviewed-test-version")
    monkeypatch.setattr(preflight, "verify_sequential_graph", lambda: None)
    report = preflight.preflight(sha, account_uuid, TEMPLATE)
    assert report["evaluated_sha"] == sha
    assert any(args[:3] == ("doctl", "harness-runtime", "validate") for args in calls)
    assert any(args[:3] == ("doctl", "harness-runtime", "create") for args in calls)
    assert all("launch" not in args and "triggers" not in args for args in calls)
    assert all("create" not in args or "--dry-run" in args for args in calls)
