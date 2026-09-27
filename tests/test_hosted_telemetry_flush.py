"""Short-lived hosted commands flush optional OTLP spans before exit."""

from types import SimpleNamespace

import pytest
from test_hosted_graph import environment

from lyme_gap_atlas_dataset_discovery import hosted_manual, hosted_shadow, observability
from lyme_gap_atlas_dataset_discovery.graph.budgets import BudgetUsage
from lyme_gap_atlas_dataset_discovery.graph.hosted import HostedConfig


@pytest.mark.parametrize(
    ("module", "profile", "run_prefix"),
    [
        (hosted_manual, "HOSTED_MANUAL", "dd-hosted-manual-"),
        (hosted_shadow, "SHADOW", "dd-shadow-"),
    ],
)
def test_hosted_entrypoints_flush_after_success(
    monkeypatch: pytest.MonkeyPatch, module: object, profile: str, run_prefix: str
) -> None:
    config = HostedConfig.from_environment({**environment(), "ATLAS_DISCOVERY_PROFILE": profile})
    flushed: list[bool] = []
    monkeypatch.setattr(module.HostedConfig, "from_environment", lambda: config)
    monkeypatch.setattr(
        module,
        "build_hosted_graph",
        lambda _config: SimpleNamespace(
            invoke=lambda _state, config: {"usage": BudgetUsage(), "final_status": "BUDGET_STOPPED"}
        ),
    )
    monkeypatch.setattr(module, "flush_dataset_discovery_tracing", lambda: flushed.append(True))
    assert (
        module.main(
            [
                "--run-id",
                run_prefix + "1" * 32,
                "--trace-id",
                "2" * 32,
                "--host-session-id",
                "sess_abc123",
            ]
        )
        == 0
    )
    assert flushed == [True]


def test_optional_provider_is_flushed_without_affecting_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushed: list[bool] = []
    monkeypatch.setattr(
        observability.trace,
        "get_tracer_provider",
        lambda: SimpleNamespace(force_flush=lambda: flushed.append(True)),
    )
    observability.flush_dataset_discovery_tracing()
    assert flushed == [True]
