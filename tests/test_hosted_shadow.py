"""Shadow proof remains bounded, manually triggered, and profile isolated."""

import importlib.util
import json
from pathlib import Path

import pytest
from test_hosted_graph import environment

from lyme_gap_atlas_dataset_discovery.graph.budgets import RunProfile
from lyme_gap_atlas_dataset_discovery.graph.hosted import HostedConfig
from lyme_gap_atlas_dataset_discovery.hosted_shadow import bounded_input

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/digitalocean/preflight.py"
spec = importlib.util.spec_from_file_location("shadow_test_preflight", SCRIPT)
assert spec is not None and spec.loader is not None
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
TEMPLATE = SCRIPT.parent / "langgraph-shadow.template.json"


def test_shadow_input_is_three_candidate_manual_and_same_model() -> None:
    config = HostedConfig.from_environment({**environment(), "ATLAS_DISCOVERY_PROFILE": "SHADOW"})
    state = bounded_input(
        config,
        run_id="dd-shadow-" + "1" * 32,
        trace_id="2" * 32,
        host_session_id="01a0e40a-e1b0-7747-9313-262a92b3cf08",
    )
    assert state["profile"] == RunProfile.SHADOW
    assert state["trigger_type"] == "MANUAL"
    assert state["execution_key"] == "shadow:" + state["requested_run_id"]
    assert state["limits"].candidates == 3
    assert state["limits"].pages == 1
    assert state["limits"].candidate_concurrency == 1
    assert state["model_fingerprint"] == config.model_fingerprint


def test_shadow_refuses_manual_profile() -> None:
    config = HostedConfig.from_environment(environment())
    with pytest.raises(ValueError, match="SHADOW profile"):
        bounded_input(
            config,
            run_id="dd-shadow-" + "1" * 32,
            trace_id="2" * 32,
            host_session_id="sess_abc123",
        )


def test_shadow_spec_is_separate_and_manual_preflight_rejects_it() -> None:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    values = {name: "reviewed-nonsecret" for name in preflight.NONSECRET_VARS}
    values["SNOWFLAKE_EGRESS_HOST"] = "account.snowflakecomputing.com"
    rendered = preflight.render_spec(template, "a" * 40, values, profile="SHADOW")
    assert rendered["env"]["ATLAS_DISCOVERY_PROFILE"] == "SHADOW"
    assert rendered["permissions"] == {"default": "ask"}
    assert rendered["secrets"]["GITHUB_TOKEN"] == "oauth/github"
    with pytest.raises(preflight.PreflightError, match="profile differs"):
        preflight.render_spec(template, "a" * 40, values)
