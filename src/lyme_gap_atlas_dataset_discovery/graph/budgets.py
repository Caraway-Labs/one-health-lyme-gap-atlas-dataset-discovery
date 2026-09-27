"""Validated v1 execution profiles and deterministic budget accounting."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunProfile(StrEnum):
    FIXTURE = "FIXTURE"
    DEV_MANUAL = "DEV_MANUAL"
    HOSTED_MANUAL = "HOSTED_MANUAL"
    SHADOW = "SHADOW"
    SCHEDULED = "SCHEDULED"


class BudgetExceeded(ValueError):
    """A hard profile ceiling was reached before the next operation."""


class BudgetLimit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: int = Field(gt=0, le=100)
    pages: int = Field(gt=0, le=20)
    graph_steps: int = Field(gt=0, le=1200)
    model_calls: int = Field(ge=0, le=200)
    tool_calls: int = Field(ge=0, le=500)
    retries_per_operation: int = Field(ge=0, le=2)
    candidate_concurrency: int = Field(default=1, ge=1, le=1)
    elapsed_seconds: int = Field(gt=0, le=3600)
    input_tokens: int = Field(ge=0, le=500_000)
    output_tokens: int = Field(ge=0, le=100_000)
    evidence_bytes: int = Field(gt=0, le=4 * 1024 * 1024)
    retained_state_bytes: int = Field(gt=0, le=1024 * 1024)
    estimated_spend_cents: int = Field(ge=0, le=10_000)


class RunBudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: RunProfile
    limits: BudgetLimit
    price_table_version: str | None = None

    @model_validator(mode="after")
    def unattended_gate(self) -> "RunBudgetConfig":
        if self.profile == RunProfile.SCHEDULED:
            raise ValueError("scheduled operation is disabled pending explicit owner approval")
        if (
            self.profile in {RunProfile.HOSTED_MANUAL, RunProfile.SHADOW}
            and not self.price_table_version
        ):
            raise ValueError("hosted model use requires reviewed price metadata")
        return self


PROFILE_DEFAULTS: dict[RunProfile, BudgetLimit] = {
    RunProfile.FIXTURE: BudgetLimit(
        candidates=5,
        pages=2,
        graph_steps=100,
        model_calls=10,
        tool_calls=30,
        retries_per_operation=0,
        elapsed_seconds=120,
        input_tokens=20_000,
        output_tokens=4_000,
        evidence_bytes=256 * 1024,
        retained_state_bytes=128 * 1024,
        estimated_spend_cents=0,
    ),
    RunProfile.DEV_MANUAL: BudgetLimit(
        candidates=20,
        pages=4,
        graph_steps=300,
        model_calls=40,
        tool_calls=120,
        retries_per_operation=2,
        elapsed_seconds=900,
        input_tokens=100_000,
        output_tokens=20_000,
        evidence_bytes=1024 * 1024,
        retained_state_bytes=256 * 1024,
        estimated_spend_cents=200,
    ),
    RunProfile.HOSTED_MANUAL: BudgetLimit(
        candidates=20,
        pages=4,
        graph_steps=300,
        model_calls=40,
        tool_calls=120,
        retries_per_operation=2,
        elapsed_seconds=900,
        input_tokens=100_000,
        output_tokens=20_000,
        evidence_bytes=1024 * 1024,
        retained_state_bytes=256 * 1024,
        estimated_spend_cents=200,
    ),
    RunProfile.SHADOW: BudgetLimit(
        candidates=50,
        pages=10,
        graph_steps=650,
        model_calls=100,
        tool_calls=250,
        retries_per_operation=2,
        elapsed_seconds=1800,
        input_tokens=250_000,
        output_tokens=50_000,
        evidence_bytes=2 * 1024 * 1024,
        retained_state_bytes=512 * 1024,
        estimated_spend_cents=500,
    ),
}


class BudgetUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: int = Field(default=0, ge=0)
    pages: int = Field(default=0, ge=0)
    graph_steps: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    elapsed_seconds: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    evidence_bytes: int = Field(default=0, ge=0)
    retained_state_bytes: int = Field(default=0, ge=0)
    estimated_spend_cents: int = Field(default=0, ge=0)


def charge_budget(usage: BudgetUsage, limits: BudgetLimit, **increments: int) -> BudgetUsage:
    """Validate a reservation before an operation starts; actual usage is charged later."""
    known = set(BudgetUsage.model_fields)
    if unknown := set(increments) - known:
        raise ValueError(f"unknown budget dimensions: {sorted(unknown)}")
    if any(value < 0 for value in increments.values()):
        raise ValueError("budget increments must be nonnegative")
    updated = usage.model_copy(
        update={name: getattr(usage, name) + value for name, value in increments.items()}
    )
    for name in known:
        if getattr(updated, name) > getattr(limits, name):
            raise BudgetExceeded(f"budget exhausted: {name}")
    return updated


def remaining_budget(usage: BudgetUsage, limits: BudgetLimit) -> dict[str, int]:
    """Expose remaining run allowance without duplicating budget policy."""
    return {name: getattr(limits, name) - getattr(usage, name) for name in BudgetUsage.model_fields}
