"""Offline configuration checks and credentialed dry-run preflight; no session creation."""

import argparse
import copy
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

REPO = "https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-dataset-discovery.git"
GH_REPO = "Caraway-Labs/one-health-lyme-gap-atlas-dataset-discovery"
ROOT = Path(__file__).resolve().parents[2]
REQUIRED_NODES = {
    "initialize_run",
    "create_run",
    "load_discovery_context",
    "load_candidate_batch",
    "select_next_candidate",
    "assess_evidence_sufficiency",
    "analyze_candidate_relationship",
    "classify_and_score_candidate",
    "generate_recommendation_rationale",
    "propose_search_expansions",
    "validate_candidate_result",
    "persist_recommendation",
    "record_candidate_outcome",
    "build_run_summary",
    "finalize_run",
}
NONSECRET_VARS = {
    "ATLAS_DISCOVERY_SNAPSHOT_ID",
    "ATLAS_DISCOVERY_SEARCH_FINGERPRINT",
    "ATLAS_PRICE_TABLE_VERSION",
    "ATLAS_MODEL_CONFIG_FINGERPRINT",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_WAREHOUSE",
}
SECRET_VARS = {
    "ATLAS_DD_DEV_OPENAI_API_KEY",
    "ATLAS_DD_DEV_SNOWFLAKE_PAT",
}
SHADOW_SECRET_VARS = SECRET_VARS | {
    "ATLAS_DD_DEV_ARIZE_API_KEY",
    "ATLAS_DD_DEV_ARIZE_SPACE_ID",
}
ARIZE_OTLP_ENDPOINT = "https://otlp.arize.com/v1/traces"
SHADOW_RESOURCE_ATTRIBUTES = (
    "openinference.project.name=atlas-dataset-discovery,atlas.environment=DEV,atlas.mode=SHADOW"
)
SECRET_SENTINEL = "REQUIRED_INJECTION_VIA_SECRET_FLAG"
EGRESS_VARS = {"SNOWFLAKE_EGRESS_HOST"}
HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
SHA = re.compile(r"^[0-9a-f]{40}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class PreflightError(ValueError):
    """A launch gate was not proven."""


def _command(*args: str, timeout: int = 30) -> str:
    actual_args = args
    selected_doctl = os.environ.get("ATLAS_DOCTL_BIN")
    if args[0] == "doctl" and selected_doctl:
        binary = Path(selected_doctl)
        if not binary.is_absolute() or not binary.is_file() or binary.name.lower() != "doctl.exe":
            raise PreflightError("ATLAS_DOCTL_BIN is not an installed doctl executable")
        actual_args = (str(binary), *args[1:])
    try:
        result = subprocess.run(
            actual_args, capture_output=True, text=True, check=False, timeout=timeout, cwd=ROOT
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreflightError(f"unavailable command: {args[0]}") from error
    if result.returncode != 0:
        # CLI errors may include account context, URLs or credentials. Never print them.
        raise PreflightError(f"preflight command failed: {' '.join(args[:2])}")
    return result.stdout.strip()


def installed_doctl_version() -> str:
    """Record --version first; older doctl uses the `version` subcommand."""
    try:
        output = _command("doctl", "--version")
    except PreflightError:
        output = _command("doctl", "version")
    match = re.search(r"(?:doctl\s+)?version\s+(\S+)", output, re.IGNORECASE)
    if match is None:
        raise PreflightError("doctl version could not be identified")
    return match.group(1)


def validate_graph_nodes(nodes: set[str]) -> None:
    if not nodes >= REQUIRED_NODES:
        raise PreflightError("langgraph.json still exports a smoke or incomplete graph")


def verify_sequential_graph(profile: str = "HOSTED_MANUAL") -> None:
    manifest = json.loads((ROOT / "langgraph.json").read_text(encoding="utf-8"))
    if manifest.get("python_version") != "3.12":
        raise PreflightError("hosted Python version differs from application requirement")
    if "env" in manifest:
        raise PreflightError("hosted manifest must use managed environment, not a local .env file")
    exported = manifest.get("graphs", {}).get("dataset_discovery")
    if not isinstance(exported, str) or not exported.endswith(":graph"):
        raise PreflightError("langgraph.json lacks the compiled Dataset Discovery graph")
    if not exported.endswith("graph/hosted_entrypoint.py:graph"):
        raise PreflightError("hosted manifest must export the guarded sequential graph")
    # Compile the same graph factory as the hosted entrypoint with synthetic
    # credentials. Local preflight must never require secret values in env.
    from lyme_gap_atlas_dataset_discovery.graph.hosted import HostedConfig, build_hosted_graph
    from lyme_gap_atlas_dataset_discovery.model_policy import LunaPriceTable, ModelPolicy

    graph_env = {
        "ATLAS_DISCOVERY_PROFILE": profile,
        "FRAMEWORK_REPO_SHA": "a" * 40,
        "ATLAS_DISCOVERY_SNAPSHOT_ID": "preflight-snapshot",
        "ATLAS_DISCOVERY_SEARCH_FINGERPRINT": "b" * 64,
        "ATLAS_PRICE_TABLE_VERSION": LunaPriceTable.standard_v1().version,
        "ATLAS_MODEL_CONFIG_FINGERPRINT": (
            ModelPolicy.luna_low_v2_4096().fingerprint
            if profile == "SHADOW"
            else ModelPolicy.luna_low_v2().fingerprint
        ),
        "ATLAS_MODEL_PROVIDER": "openai",
        "ATLAS_MODEL_ID": "gpt-6-luna",
        "ATLAS_MODEL_API": "responses",
        "ATLAS_MODEL_REASONING_EFFORT": "low",
        "ATLAS_MODEL_POLICY_VERSION": "atlas-dd-model-v1",
        "ATLAS_DD_DEV_OPENAI_API_KEY": "synthetic-preflight-only",
        "SNOWFLAKE_ACCOUNT": "preflight-account",
        "SNOWFLAKE_USER": "PREFLIGHT_SERVICE",
        "SNOWFLAKE_ROLE": "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME",
        "SNOWFLAKE_DATABASE": "ONE_HEALTH_LYME_GAP_ATLAS_DEV",
        "SNOWFLAKE_WAREHOUSE": "OH_LYME_DEV_WH",
        "ATLAS_DD_DEV_SNOWFLAKE_PAT": "synthetic-preflight-only",
    }
    config = HostedConfig.from_environment(graph_env)
    from lyme_gap_atlas_dataset_discovery.observability import isolated_fixture_tracing

    def no_connection(_config: HostedConfig) -> Any:
        raise PreflightError("graph compilation unexpectedly opened Snowflake")

    with isolated_fixture_tracing():
        nodes = set(build_hosted_graph(config, raw_connect=no_connection).get_graph().nodes)
    validate_graph_nodes(nodes)


def render_spec(
    template: dict[str, Any],
    sha: str,
    environment: dict[str, str],
    *,
    profile: str = "HOSTED_MANUAL",
) -> dict[str, Any]:
    """Resolve nonsecret fields only; doctl expands secret references at dry-run."""
    if not SHA.fullmatch(sha):
        raise PreflightError("FRAMEWORK_REPO_SHA must be an exact 40-character commit")
    if template.get("size") != "mars-2vcpu-4gb" or template.get("idle_timeout") != "10m":
        raise PreflightError("session size or idle timeout differs from reviewed template")
    if template.get("agent") != "langgraph":
        raise PreflightError("Harness Runtime must use the LangGraph framework")
    values = template.get("env")
    secrets = template.get("secrets")
    if not isinstance(values, dict) or not isinstance(secrets, dict):
        raise PreflightError("environment spec has no env/secrets separation")
    if values.get("FRAMEWORK_REPO") != REPO or values.get("FRAMEWORK_REPO_SHA") != (
        "${FRAMEWORK_REPO_SHA}"
    ):
        raise PreflightError("framework repository or SHA template differs from reviewed contract")
    if (
        profile not in {"HOSTED_MANUAL", "SHADOW"}
        or values.get("ATLAS_DISCOVERY_PROFILE") != profile
    ):
        raise PreflightError("hosted profile differs from reviewed preflight")
    secret_vars = SHADOW_SECRET_VARS if profile == "SHADOW" else SECRET_VARS
    if set(secrets) != secret_vars | {"GITHUB_TOKEN"} or secrets.get("GITHUB_TOKEN") != (
        "oauth/github"
    ):
        raise PreflightError("private clone or managed secret inventory differs from contract")
    for name in secret_vars:
        if secrets[name] != "${" + name + "}":
            raise PreflightError(f"managed secret reference unavailable: {name}")
    if profile == "SHADOW" and (
        values.get("OTEL_EXPORTER_OTLP_ENDPOINT") != ARIZE_OTLP_ENDPOINT
        or values.get("OTEL_RESOURCE_ATTRIBUTES") != SHADOW_RESOURCE_ATTRIBUTES
    ):
        raise PreflightError("SHADOW Arize AX OTLP routing differs from reviewed contract")
    rendered = copy.deepcopy(template)
    rendered["env"]["FRAMEWORK_REPO_SHA"] = sha
    # doctl expands ${VAR} before --secret flags are applied. A noncredential
    # sentinel lets validate inspect the spec; create --dry-run and the real
    # session must override both slots with file-backed --secret flags.
    for name in secret_vars:
        rendered["secrets"][name] = SECRET_SENTINEL
    for name in NONSECRET_VARS:
        if values.get(name) != "${" + name + "}" or not environment.get(name):
            raise PreflightError(f"nonsecret environment field unavailable: {name}")
        rendered["env"][name] = environment[name]
    egress = rendered.get("egress")
    if not isinstance(egress, dict) or set(egress) != {"allow_hosts"}:
        raise PreflightError("hosted egress must be an explicit host allowlist")
    hosts = egress.get("allow_hosts")
    if not isinstance(hosts, list) or "api.openai.com" not in hosts:
        raise PreflightError("OpenAI provider egress is not allowlisted")
    if profile == "SHADOW" and hosts.count("otlp.arize.com") != 1:
        raise PreflightError("SHADOW Arize AX egress is not allowlisted")
    for name in EGRESS_VARS:
        marker = "${" + name + "}"
        value = environment.get(name)
        if hosts.count(marker) != 1 or not value or not HOST.fullmatch(value):
            raise PreflightError(f"required egress host unavailable: {name}")
        if name == "SNOWFLAKE_EGRESS_HOST" and not value.endswith(".snowflakecomputing.com"):
            raise PreflightError("Snowflake egress host is not an account endpoint")
        hosts[hosts.index(marker)] = value
    if any(not HOST.fullmatch(host) for host in hosts) or len(hosts) != len(set(hosts)):
        raise PreflightError("egress allowlist contains an invalid or duplicate host")
    if any("KEY" in name or "TOKEN" in name or "PAT" in name for name in rendered["env"]):
        raise PreflightError("credential-like field found in public environment values")
    expected_hosts = {
        "api.openai.com",
        "github.com",
        "api.github.com",
        "pypi.org",
        "files.pythonhosted.org",
        environment["SNOWFLAKE_EGRESS_HOST"],
    }
    if profile == "SHADOW":
        expected_hosts.add("otlp.arize.com")
    if set(hosts) != expected_hosts:
        raise PreflightError("egress differs from reviewed host inventory")
    expected_env = NONSECRET_VARS | {
        "FRAMEWORK_REPO",
        "FRAMEWORK_REPO_SHA",
        "ATLAS_DISCOVERY_PROFILE",
        "ATLAS_MODEL_PROVIDER",
        "ATLAS_MODEL_ID",
        "ATLAS_MODEL_API",
        "ATLAS_MODEL_REASONING_EFFORT",
        "ATLAS_MODEL_POLICY_VERSION",
    }
    if profile == "SHADOW":
        expected_env |= {"OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_RESOURCE_ATTRIBUTES"}
    if set(rendered["env"]) != expected_env:
        raise PreflightError("public environment differs from reviewed inventory")
    from lyme_gap_atlas_dataset_discovery.graph.hosted import HostedConfig

    try:
        HostedConfig.from_environment(
            {
                **rendered["env"],
                "ATLAS_DD_DEV_OPENAI_API_KEY": "synthetic-preflight-only",
                "ATLAS_DD_DEV_SNOWFLAKE_PAT": "synthetic-preflight-only",
            }
        )
    except ValueError:
        raise PreflightError("rendered configuration differs from reviewed DEV contract") from None
    if rendered.get("permissions") != {"default": "ask"}:
        raise PreflightError("manual permission policy differs from reviewed contract")
    return rendered


def offline_preflight(
    sha: str,
    template_path: Path,
    *,
    profile: str = "HOSTED_MANUAL",
    environment: dict[str, str] | None = None,
) -> dict[str, str | bool]:
    """Validate local nonsecret configuration only; no CLI, secret file or connection."""
    values = (
        {name: os.environ.get(name, "") for name in NONSECRET_VARS | EGRESS_VARS}
        if environment is None
        else environment
    )
    template = json.loads(template_path.read_text(encoding="utf-8"))
    render_spec(template, sha, values, profile=profile)
    verify_sequential_graph(profile)
    return {
        "proof_scope": "OFFLINE_CONFIGURATION",
        "requested_sha": sha,
        "profile": profile,
        "result": "OFFLINE_CONFIGURATION_PASSED_RUNTIME_PROOF_PENDING",
        "runtime_acceptance": False,
        "prod_readiness": False,
        "session_lifetime_control": "OPERATOR_REQUIRED_NOT_ENFORCED",
        "platform_cost_cap": "NOT_ENFORCED_BY_GRAPH_OR_IDLE_TIMEOUT",
    }


def preflight(
    sha: str, account_uuid: str, template_path: Path, *, profile: str = "HOSTED_MANUAL"
) -> dict[str, str]:
    if not SHA.fullmatch(sha) or not UUID.fullmatch(account_uuid):
        raise PreflightError("exact commit SHA and intended account UUID are required")
    version = installed_doctl_version()
    _command("doctl", "harness-runtime", "--help")
    _command("doctl", "harness-runtime", "validate", "--help")
    account = _command("doctl", "account", "get", "--format", "UUID", "--no-header")
    if account.strip() != account_uuid:
        raise PreflightError("active DigitalOcean account differs from intended team")
    verify_sequential_graph(profile)
    if _command("git", "rev-parse", "HEAD") != sha:
        raise PreflightError("local checkout differs from evaluated SHA")
    if _command("git", "status", "--porcelain"):
        raise PreflightError("evaluated checkout is not clean")
    remote = _command("gh", "api", f"repos/{GH_REPO}/commits/{sha}", "--jq", ".sha")
    if remote != sha:
        raise PreflightError("evaluated SHA is unavailable in private GitHub repository")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    rendered = render_spec(template, sha, dict(os.environ), profile=profile)
    secret_flags: list[str] = []
    secret_vars = SHADOW_SECRET_VARS if profile == "SHADOW" else SECRET_VARS
    for name in sorted(secret_vars):
        file_name = os.environ.get(name + "_FILE")
        if not file_name:
            raise PreflightError(f"managed secret file reference unavailable: {name}")
        secret_path = Path(file_name)
        if (
            not secret_path.is_absolute()
            or not secret_path.is_file()
            or secret_path.stat().st_size == 0
        ):
            raise PreflightError(f"managed secret file is unavailable or empty: {name}")
        if secret_path.is_relative_to(ROOT):
            raise PreflightError("managed secret file must remain outside the repository")
        secret_flags.extend(("--secret", f"{name}=@{secret_path}"))
    with tempfile.TemporaryDirectory(prefix="atlas-discovery-preflight-") as directory:
        spec = Path(directory) / "langgraph-agent.json"
        spec.write_text(json.dumps(rendered), encoding="utf-8")
        _command("doctl", "harness-runtime", "validate", "--spec", str(spec))
        _command(
            "doctl",
            "harness-runtime",
            "create",
            "--spec",
            str(spec),
            "--dry-run",
            *secret_flags,
        )
    return {
        "doctl_version": version,
        "account_uuid": account_uuid,
        "evaluated_sha": sha,
        "spec_template": str(template_path.relative_to(ROOT)),
        "result": "LOCAL_PREFLIGHT_PASSED_TEAM_CLONE_AND_DEV_PROOF_PENDING",
        "proof_scope": "CREDENTIALED_DRY_RUN",
        "session_lifetime_control": "OPERATOR_REQUIRED_NOT_ENFORCED",
        "platform_cost_cap": "NOT_ENFORCED_BY_GRAPH_OR_IDLE_TIMEOUT",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Dataset Discovery hosted preflight")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--account-uuid")
    parser.add_argument("--offline", action="store_true", help="local nonsecret checks only")
    parser.add_argument(
        "--template", type=Path, default=ROOT / "deploy/digitalocean/langgraph-agent.template.json"
    )
    args = parser.parse_args()
    try:
        if args.offline:
            report = offline_preflight(args.sha, args.template)
        else:
            if args.account_uuid is None:
                raise PreflightError("credentialed preflight requires intended account UUID")
            report = preflight(args.sha, args.account_uuid, args.template)
        print(json.dumps(report, indent=2))
        return 0
    except PreflightError as error:
        print(f"Hosted preflight blocked: {error}")
        return 1
    except (OSError, ValueError):
        print("Hosted preflight blocked: invalid or unavailable configuration")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
