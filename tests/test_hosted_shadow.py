"""Shadow proof remains bounded, manually triggered, and profile isolated."""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from test_hosted_graph import environment

from lyme_gap_atlas_dataset_discovery.graph.budgets import (
    BudgetExceeded,
    BudgetUsage,
    RunProfile,
    charge_budget,
)
from lyme_gap_atlas_dataset_discovery.graph.hosted import HostedConfig
from lyme_gap_atlas_dataset_discovery.hosted_shadow import bounded_input
from lyme_gap_atlas_dataset_discovery.model_policy import ModelPolicy

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/digitalocean/preflight.py"
spec = importlib.util.spec_from_file_location("shadow_test_preflight", SCRIPT)
assert spec is not None and spec.loader is not None
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)
TEMPLATE = SCRIPT.parent / "langgraph-shadow.template.json"


def shadow_environment() -> dict[str, str]:
    return {
        **environment(),
        "ATLAS_DISCOVERY_PROFILE": "SHADOW",
        "ATLAS_MODEL_CONFIG_FINGERPRINT": ModelPolicy.luna_low_v2_4096().fingerprint,
    }


def test_shadow_input_is_three_candidate_manual_and_same_model() -> None:
    config = HostedConfig.from_environment(shadow_environment())
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
    assert state["limits"].output_tokens == 12_000
    assert state["limits"].output_tokens < 3 * 4096
    with pytest.raises(BudgetExceeded, match="output_tokens"):
        charge_budget(BudgetUsage(output_tokens=10_000), state["limits"], output_tokens=4096)
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


def test_shadow_selected_candidates_are_bounded_and_part_of_run_identity() -> None:
    config = HostedConfig.from_environment(shadow_environment())
    selected = ("candidate:" + "1" * 32, "candidate:" + "2" * 32)
    state = bounded_input(
        config,
        run_id="dd-shadow-" + "1" * 32,
        trace_id="2" * 32,
        host_session_id="01a0e40a-e1b0-7747-9313-262a92b3cf08",
        selected_candidate_ids=selected,
    )
    assert (
        state["tool_versions"]["candidate_selection_v1"]
        == hashlib.sha256("|".join(selected).encode()).hexdigest()
    )
    assert state["model_fingerprint"] == config.model_fingerprint
    for invalid in (selected[::-1], selected + (selected[0],), ("candidate:bad",)):
        with pytest.raises(ValueError, match="candidate selection"):
            bounded_input(
                config,
                run_id="dd-shadow-" + "1" * 32,
                trace_id="2" * 32,
                host_session_id="01a0e40a-e1b0-7747-9313-262a92b3cf08",
                selected_candidate_ids=invalid,
            )


def test_shadow_spec_is_separate_and_manual_preflight_rejects_it() -> None:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    values = {name: "reviewed-nonsecret" for name in preflight.NONSECRET_VARS}
    values["SNOWFLAKE_EGRESS_HOST"] = "account.snowflakecomputing.com"
    rendered = preflight.render_spec(template, "a" * 40, values, profile="SHADOW")
    assert rendered["env"]["ATLAS_DISCOVERY_PROFILE"] == "SHADOW"
    assert rendered["permissions"] == {"default": "ask"}
    assert rendered["secrets"]["GITHUB_TOKEN"] == "oauth/github"
    assert set(rendered["secrets"]) == preflight.SHADOW_SECRET_VARS | {"GITHUB_TOKEN"}
    assert all(
        rendered["secrets"][name] == preflight.SECRET_SENTINEL
        for name in preflight.SHADOW_SECRET_VARS
    )
    assert rendered["env"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == preflight.ARIZE_OTLP_ENDPOINT
    assert "otlp.arize.com" in rendered["egress"]["allow_hosts"]
    with pytest.raises(preflight.PreflightError, match="profile differs"):
        preflight.render_spec(template, "a" * 40, values)


def test_shadow_rejects_missing_project_route_or_arize_egress() -> None:
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    values = {name: "reviewed-nonsecret" for name in preflight.NONSECRET_VARS}
    values["SNOWFLAKE_EGRESS_HOST"] = "account.snowflakecomputing.com"
    template["env"]["OTEL_RESOURCE_ATTRIBUTES"] = "service.name=wrong-project"
    with pytest.raises(preflight.PreflightError, match="routing"):
        preflight.render_spec(template, "a" * 40, values, profile="SHADOW")
    template["env"]["OTEL_RESOURCE_ATTRIBUTES"] = preflight.SHADOW_RESOURCE_ATTRIBUTES
    template["egress"]["allow_hosts"].remove("otlp.arize.com")
    with pytest.raises(preflight.PreflightError, match="egress"):
        preflight.render_spec(template, "a" * 40, values, profile="SHADOW")
