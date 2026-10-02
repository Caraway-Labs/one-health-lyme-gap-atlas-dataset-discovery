"""Hosted preflight must reject floating code and the foundation smoke graph."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lyme_gap_atlas_dataset_discovery.model_policy import LunaPriceTable, ModelPolicy

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/digitalocean/preflight.py"
TEMPLATE = SCRIPT.parent / "langgraph-agent.template.json"
spec = importlib.util.spec_from_file_location("hosted_preflight", SCRIPT)
assert spec is not None and spec.loader is not None
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def environment() -> dict[str, str]:
    return {
        "ATLAS_DISCOVERY_SNAPSHOT_ID": "synthetic-snapshot",
        "ATLAS_DISCOVERY_SEARCH_FINGERPRINT": "b" * 64,
        "ATLAS_PRICE_TABLE_VERSION": LunaPriceTable.standard_v1().version,
        "ATLAS_MODEL_CONFIG_FINGERPRINT": ModelPolicy.luna_low_v2().fingerprint,
        "SNOWFLAKE_ACCOUNT": "synthetic-account",
        "SNOWFLAKE_USER": "SYNTHETIC_SERVICE",
        "SNOWFLAKE_ROLE": "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME",
        "SNOWFLAKE_DATABASE": "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        "SNOWFLAKE_WAREHOUSE": "FIXTURE_WH",
        **{name: "test-secret" for name in preflight.SECRET_VARS},
        "SNOWFLAKE_EGRESS_HOST": "account.snowflakecomputing.com",
    }


def test_spec_renders_exact_sha_without_copying_secrets_into_env() -> None:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    rendered = preflight.render_spec(template, "a" * 40, environment())
    assert rendered["env"]["FRAMEWORK_REPO_SHA"] == "a" * 40
    assert rendered["env"]["ATLAS_DISCOVERY_PROFILE"] == "HOSTED_MANUAL"
    assert rendered["secrets"]["GITHUB_TOKEN"] == "oauth/github"
    assert all(
        rendered["secrets"][name] == preflight.SECRET_SENTINEL for name in preflight.SECRET_VARS
    )
    assert "test-secret" not in json.dumps(rendered)
    assert "api.openai.com" in rendered["egress"]["allow_hosts"]
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


def test_manifest_exports_real_sequential_graph_without_operator_secrets() -> None:
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
    tmp_path: Path,
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
    for name in preflight.SECRET_VARS:
        path = tmp_path / (name + ".txt")
        path.write_text("synthetic-test-value", encoding="utf-8")
        monkeypatch.setenv(name + "_FILE", str(path))
    monkeypatch.setattr(preflight, "_command", command)
    monkeypatch.setattr(preflight, "installed_doctl_version", lambda: "reviewed-test-version")
    monkeypatch.setattr(preflight, "verify_sequential_graph", lambda _profile: None)
    report = preflight.preflight(sha, account_uuid, TEMPLATE)
    assert report["evaluated_sha"] == sha
    assert any(args[:3] == ("doctl", "harness-runtime", "validate") for args in calls)
    assert any(args[:3] == ("doctl", "harness-runtime", "create") for args in calls)
    assert all("launch" not in args and "triggers" not in args for args in calls)
    assert all("create" not in args or "--dry-run" in args for args in calls)


@pytest.mark.parametrize("profile", ["HOSTED_MANUAL", "SHADOW"])
@pytest.mark.parametrize(
    "name,value",
    [
        ("SNOWFLAKE_DATABASE", "ONE_HEALTH_LYME_GAP_ATLAS_PROD"),
        ("SNOWFLAKE_ROLE", "OH_LYME_PROD_DATASET_DISCOVERY_RUNTIME"),
        ("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        ("SNOWFLAKE_USER", "unreviewed principal"),
        ("ATLAS_MODEL_CONFIG_FINGERPRINT", "0" * 64),
        ("ATLAS_PRICE_TABLE_VERSION", "unreviewed-price"),
        ("ATLAS_DISCOVERY_SEARCH_FINGERPRINT", "not-a-fingerprint"),
    ],
)
def test_render_uses_existing_dev_runtime_configuration_gate(
    profile: str,
    name: str,
    value: str,
) -> None:
    template_path = (
        TEMPLATE if profile == "HOSTED_MANUAL" else SCRIPT.parent / "langgraph-shadow.template.json"
    )
    template = json.loads(template_path.read_text())
    values = environment()
    if profile == "SHADOW":
        values["ATLAS_MODEL_CONFIG_FINGERPRINT"] = ModelPolicy.luna_low_v2_4096().fingerprint
    values[name] = value
    with pytest.raises(preflight.PreflightError, match="reviewed DEV contract"):
        preflight.render_spec(template, "a" * 40, values, profile=profile)


@pytest.mark.parametrize("field,value", [("size", "unreviewed-size"), ("idle_timeout", "60m")])
def test_session_template_changes_need_review(field: str, value: str) -> None:
    template = json.loads(TEMPLATE.read_text())
    template[field] = value
    with pytest.raises(preflight.PreflightError, match="size or idle timeout"):
        preflight.render_spec(template, "a" * 40, environment())


def test_additional_egress_or_public_configuration_is_rejected() -> None:
    template = json.loads(TEMPLATE.read_text())
    template["egress"]["allow_hosts"].append("unreviewed.example")
    with pytest.raises(preflight.PreflightError, match="host inventory"):
        preflight.render_spec(template, "a" * 40, environment())
    template = json.loads(TEMPLATE.read_text())
    template["env"]["UNREVIEWED_TOOLSET"] = "tool-catalog"
    with pytest.raises(preflight.PreflightError, match="environment.*inventory"):
        preflight.render_spec(template, "a" * 40, environment())


@pytest.mark.parametrize("profile", ["HOSTED_MANUAL", "SHADOW"])
def test_offline_preflight_requires_no_cli_secret_file_or_connection(
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    template_path = (
        TEMPLATE if profile == "HOSTED_MANUAL" else SCRIPT.parent / "langgraph-shadow.template.json"
    )
    values = environment()
    if profile == "SHADOW":
        values["ATLAS_MODEL_CONFIG_FINGERPRINT"] = ModelPolicy.luna_low_v2_4096().fingerprint
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for name in preflight.SHADOW_SECRET_VARS:
        monkeypatch.setenv(name + "_FILE", "nonexistent-private-file")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline preflight invoked an external command or exporter")

    monkeypatch.setattr(preflight, "_command", forbidden)
    monkeypatch.setattr(
        "lyme_gap_atlas_dataset_discovery.observability.configure_tracing", forbidden
    )
    report = preflight.offline_preflight("a" * 40, template_path, profile=profile)
    assert report["proof_scope"] == "OFFLINE_CONFIGURATION"
    assert report["runtime_acceptance"] is False
    assert report["prod_readiness"] is False
    assert report["session_lifetime_control"] == "OPERATOR_REQUIRED_NOT_ENFORCED"
    assert report["platform_cost_cap"] == "NOT_ENFORCED_BY_GRAPH_OR_IDLE_TIMEOUT"
    assert "test-secret" not in json.dumps(report)
    assert "nonexistent-private-file" not in json.dumps(report)


def test_offline_cli_does_not_require_account_or_expose_local_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    for name, value in environment().items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("sys.argv", ["preflight.py", "--offline", "--sha", "a" * 40])
    assert preflight.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["requested_sha"] == "a" * 40
    missing = tmp_path / "private-missing-template.json"
    monkeypatch.setattr(
        "sys.argv", ["preflight.py", "--offline", "--sha", "a" * 40, "--template", str(missing)]
    )
    assert preflight.main() == 1
    output = capsys.readouterr().out
    assert "invalid or unavailable configuration" in output
    assert str(tmp_path) not in output
