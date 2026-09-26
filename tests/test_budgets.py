"""Run profiles remain within reviewed ceilings and scheduling fails closed."""

import pytest
from pydantic import ValidationError

from lyme_gap_atlas_dataset_discovery.graph.budgets import (
    PROFILE_DEFAULTS,
    BudgetLimit,
    BudgetUsage,
    RunBudgetConfig,
    RunProfile,
    charge_budget,
)


def test_all_active_defaults_are_valid_and_sequential() -> None:
    assert set(PROFILE_DEFAULTS) == set(RunProfile) - {RunProfile.SCHEDULED}
    for profile, limits in PROFILE_DEFAULTS.items():
        assert limits.candidate_concurrency == 1
        RunBudgetConfig(
            profile=profile,
            limits=limits,
            price_table_version="reviewed-v1" if profile != RunProfile.FIXTURE else None,
        )


def test_scheduled_cannot_be_enabled_by_a_caller() -> None:
    with pytest.raises(ValidationError, match="disabled pending explicit owner approval"):
        RunBudgetConfig(
            profile=RunProfile.SCHEDULED,
            limits=PROFILE_DEFAULTS[RunProfile.SHADOW],
            price_table_version="reviewed-v1",
        )


def test_hosted_requires_reviewed_price_metadata() -> None:
    with pytest.raises(ValidationError, match="requires reviewed price metadata"):
        RunBudgetConfig(
            profile=RunProfile.HOSTED_MANUAL, limits=PROFILE_DEFAULTS[RunProfile.HOSTED_MANUAL]
        )


def test_hard_maximum_and_sequential_processing() -> None:
    with pytest.raises(ValidationError):
        BudgetLimit.model_validate(
            {**PROFILE_DEFAULTS[RunProfile.FIXTURE].model_dump(), "candidate_concurrency": 2}
        )


def test_budget_reservation_stops_before_crossing_limit() -> None:
    limits = PROFILE_DEFAULTS[RunProfile.FIXTURE]
    usage = charge_budget(BudgetUsage(), limits, candidates=5, graph_steps=1)
    assert usage.candidates == 5
    with pytest.raises(ValueError, match="candidates"):
        charge_budget(usage, limits, candidates=1)
    with pytest.raises(ValueError, match="unknown budget dimensions"):
        charge_budget(usage, limits, arbitrary_sql=1)
