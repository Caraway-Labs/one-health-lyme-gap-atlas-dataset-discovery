"""Hosted operator invocation remains one-candidate, manual, and replayable."""

import pytest
from test_hosted_graph import environment

from lyme_gap_atlas_dataset_discovery.graph.budgets import RunProfile
from lyme_gap_atlas_dataset_discovery.graph.hosted import HostedConfig
from lyme_gap_atlas_dataset_discovery.hosted_manual import bounded_input


def test_hosted_manual_input_is_bounded_and_pinned() -> None:
    config = HostedConfig.from_environment(environment())
    state = bounded_input(
        config,
        run_id="dd-hosted-manual-" + "1" * 32,
        trace_id="2" * 32,
        host_session_id="sess_abc123",
    )
    assert state["profile"] == RunProfile.HOSTED_MANUAL
    assert state["trigger_type"] == "MANUAL"
    assert state["execution_key"] == "hosted-manual:" + state["requested_run_id"]
    assert state["code_sha"] == config.code_sha
    assert state["search_fingerprint"] == config.search_fingerprint
    assert state["model_fingerprint"] == config.model_fingerprint
    assert state["limits"].candidates == state["limits"].pages == 1
    assert state["limits"].estimated_spend_cents == 12


def test_hosted_manual_accepts_digitalocean_uuid_session_id() -> None:
    config = HostedConfig.from_environment(environment())
    session_id = "01a0e40a-e1b0-7747-9313-262a92b3cf08"
    state = bounded_input(
        config,
        run_id="dd-hosted-manual-" + "1" * 32,
        trace_id="2" * 32,
        host_session_id=session_id,
    )
    assert state["host_session_id"] == session_id


@pytest.mark.parametrize(
    ("run_id", "trace_id", "session_id"),
    [
        ("floating", "2" * 32, "sess_abc123"),
        ("dd-hosted-manual-" + "1" * 32, "invalid", "sess_abc123"),
        ("dd-hosted-manual-" + "1" * 32, "2" * 32, "other-session"),
    ],
)
def test_hosted_manual_rejects_unpinned_identity(
    run_id: str, trace_id: str, session_id: str
) -> None:
    config = HostedConfig.from_environment(environment())
    with pytest.raises(ValueError):
        bounded_input(
            config,
            run_id=run_id,
            trace_id=trace_id,
            host_session_id=session_id,
        )
