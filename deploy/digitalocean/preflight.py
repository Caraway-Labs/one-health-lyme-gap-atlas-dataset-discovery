"""Read-only Harness Runtime preflight. Never creates a session or prints secrets."""

import argparse
import copy
import importlib
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
    "validate_candidate_result",
    "persist_recommendation",
    "record_candidate_outcome",
    "build_run_summary",
    "finalize_run",
}
NONSECRET_VARS = {
    "ATLAS_DISCOVERY_SNAPSHOT_ID",
    "ATLAS_PRICE_TABLE_VERSION",
    "HARNESS_INFERENCE_BASE_URL",
    "HARNESS_INFERENCE_MODEL",
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_WAREHOUSE",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
}
SECRET_VARS = {
    "HARNESS_INFERENCE_API_KEY",
    "SNOWFLAKE_PAT",
    "OTEL_EXPORTER_OTLP_HEADERS",
}
SHA = re.compile(r"^[0-9a-f]{40}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class PreflightError(ValueError):
    """A launch gate was not proven."""


def _command(*args: str, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=timeout, cwd=ROOT
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


def verify_sequential_graph() -> None:
    manifest = json.loads((ROOT / "langgraph.json").read_text(encoding="utf-8"))
    if "env" in manifest:
        raise PreflightError("hosted manifest must use managed environment, not a local .env file")
    exported = manifest.get("graphs", {}).get("dataset_discovery")
    if not isinstance(exported, str) or not exported.endswith(":graph"):
        raise PreflightError("langgraph.json lacks the compiled Dataset Discovery graph")
    module = importlib.import_module("lyme_gap_atlas_dataset_discovery.graph.entrypoint")
    nodes = set(module.graph.get_graph().nodes)
    validate_graph_nodes(nodes)


def render_spec(template: dict[str, Any], sha: str, environment: dict[str, str]) -> dict[str, Any]:
    """Resolve nonsecret fields only; doctl expands secret references at dry-run."""
    if not SHA.fullmatch(sha):
        raise PreflightError("FRAMEWORK_REPO_SHA must be an exact 40-character commit")
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
    if values.get("ATLAS_DISCOVERY_PROFILE") != "HOSTED_MANUAL":
        raise PreflightError("first hosted profile must be HOSTED_MANUAL")
    if set(secrets) != SECRET_VARS | {"GITHUB_TOKEN"} or secrets.get("GITHUB_TOKEN") != (
        "oauth/github"
    ):
        raise PreflightError("private clone or managed secret inventory differs from contract")
    for name in SECRET_VARS:
        if secrets[name] != "${" + name + "}" or not environment.get(name):
            raise PreflightError(f"managed secret reference unavailable: {name}")
    rendered = copy.deepcopy(template)
    rendered["env"]["FRAMEWORK_REPO_SHA"] = sha
    for name in NONSECRET_VARS:
        if values.get(name) != "${" + name + "}" or not environment.get(name):
            raise PreflightError(f"nonsecret environment field unavailable: {name}")
        rendered["env"][name] = environment[name]
    if any("KEY" in name or "TOKEN" in name or "PAT" in name for name in rendered["env"]):
        raise PreflightError("credential-like field found in public environment values")
    if rendered.get("permissions") != {"default": "ask"}:
        raise PreflightError("manual permission policy differs from reviewed contract")
    return rendered


def preflight(sha: str, account_uuid: str, template_path: Path) -> dict[str, str]:
    if not SHA.fullmatch(sha) or not UUID.fullmatch(account_uuid):
        raise PreflightError("exact commit SHA and intended account UUID are required")
    version = installed_doctl_version()
    _command("doctl", "harness-runtime", "--help")
    _command("doctl", "harness-runtime", "validate", "--help")
    account = _command("doctl", "account", "get", "--format", "UUID", "--no-header")
    if account.strip() != account_uuid:
        raise PreflightError("active DigitalOcean account differs from intended team")
    verify_sequential_graph()
    if _command("git", "rev-parse", "HEAD") != sha:
        raise PreflightError("local checkout differs from evaluated SHA")
    if _command("git", "status", "--porcelain"):
        raise PreflightError("evaluated checkout is not clean")
    remote = _command("gh", "api", f"repos/{GH_REPO}/commits/{sha}", "--jq", ".sha")
    if remote != sha:
        raise PreflightError("evaluated SHA is unavailable in private GitHub repository")
    template = json.loads(template_path.read_text(encoding="utf-8"))
    rendered = render_spec(template, sha, dict(os.environ))
    with tempfile.TemporaryDirectory(prefix="atlas-discovery-preflight-") as directory:
        spec = Path(directory) / "langgraph-agent.json"
        spec.write_text(json.dumps(rendered), encoding="utf-8")
        _command("doctl", "harness-runtime", "validate", "--spec", str(spec))
        _command("doctl", "harness-runtime", "create", "--spec", str(spec), "--dry-run")
    return {
        "doctl_version": version,
        "account_uuid": account_uuid,
        "evaluated_sha": sha,
        "spec_template": str(template_path.relative_to(ROOT)),
        "result": "LOCAL_PREFLIGHT_PASSED_TEAM_CLONE_AND_DEV_PROOF_PENDING",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Dataset Discovery hosted preflight")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--account-uuid", required=True)
    parser.add_argument(
        "--template", type=Path, default=ROOT / "deploy/digitalocean/langgraph-agent.template.json"
    )
    args = parser.parse_args()
    try:
        print(json.dumps(preflight(args.sha, args.account_uuid, args.template), indent=2))
        return 0
    except (PreflightError, OSError, ValueError) as error:
        print(f"Hosted preflight blocked: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
