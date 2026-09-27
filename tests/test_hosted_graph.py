"""Hosted graph composition is import-safe and cannot downgrade authority."""

from decimal import Decimal
from typing import Any

import pytest

from lyme_gap_atlas_dataset_discovery.graph.budgets import PROFILE_DEFAULTS, RunProfile
from lyme_gap_atlas_dataset_discovery.graph.hosted import HostedConfig, build_hosted_graph


def environment() -> dict[str, str]:
    return {
        "ATLAS_DISCOVERY_PROFILE": "HOSTED_MANUAL",
        "FRAMEWORK_REPO_SHA": "a" * 40,
        "ATLAS_DISCOVERY_SNAPSHOT_ID": "snapshot-1",
        "ATLAS_PRICE_TABLE_VERSION": "owner-reviewed-1",
        "ATLAS_PRICE_INPUT_USD_PER_MILLION": "1.25",
        "ATLAS_PRICE_OUTPUT_USD_PER_MILLION": "5.00",
        "HARNESS_INFERENCE_BASE_URL": "https://model.example/v1/chat/completions",
        "HARNESS_INFERENCE_MODEL": "model-1",
        "HARNESS_INFERENCE_API_KEY": "test-secret",
        "SNOWFLAKE_ACCOUNT": "test-account",
        "SNOWFLAKE_USER": "DISCOVERY_SERVICE",
        "SNOWFLAKE_ROLE": "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME",
        "SNOWFLAKE_DATABASE": "OH_LYME_DEV",
        "SNOWFLAKE_WAREHOUSE": "OH_LYME_DEV_WH",
        "SNOWFLAKE_PAT": "test-pat",
    }


def test_compilation_does_not_connect_and_exports_full_graph() -> None:
    config = HostedConfig.from_environment(environment())
    assert config.input_usd_per_million == Decimal("1.25")

    def no_connection(_config: HostedConfig) -> Any:
        raise AssertionError("compilation must not connect")

    graph = build_hosted_graph(config, raw_connect=no_connection)
    nodes = set(graph.get_graph().nodes)
    assert {
        "initialize_run",
        "select_next_candidate",
        "persist_recommendation",
        "finalize_run",
    } <= nodes
    with pytest.raises(ValueError, match="required identity"):
        graph.invoke({})


@pytest.mark.parametrize(
    "change",
    [
        {"ATLAS_DISCOVERY_PROFILE": "FIXTURE"},
        {"SNOWFLAKE_ROLE": "ACCOUNTADMIN"},
        {"SNOWFLAKE_DATABASE": "OH_LYME_PROD"},
        {"FRAMEWORK_REPO_SHA": "main"},
        {"ATLAS_PRICE_INPUT_USD_PER_MILLION": "-1"},
    ],
)
def test_hosted_authority_and_price_configuration_fail_closed(change: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        HostedConfig.from_environment({**environment(), **change})


def test_secret_or_price_missing_prevents_graph_export() -> None:
    values = environment()
    del values["SNOWFLAKE_PAT"]
    with pytest.raises(ValueError, match="missing required"):
        HostedConfig.from_environment(values)


def test_effective_snowflake_identity_is_checked_before_business_sql() -> None:
    config = HostedConfig.from_environment(environment())
    statements: list[str] = []
    closed: list[bool] = []

    class Cursor:
        def execute(self, sql: str, *_args: Any, **_kwargs: Any) -> "Cursor":
            statements.append(sql)
            return self

        def fetchone(self) -> tuple[str, ...] | None:
            return (
                "OTHER_USER",
                config.snowflake_role,
                config.snowflake_database,
                config.snowflake_warehouse,
            )

        def close(self) -> None:
            pass

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def close(self) -> None:
            closed.append(True)

    graph = build_hosted_graph(config, raw_connect=lambda _config: Connection())
    state = {
        "execution_key": "manual-1",
        "requested_run_id": "run-1",
        "profile": RunProfile.HOSTED_MANUAL,
        "trigger_type": "MANUAL",
        "code_sha": config.code_sha,
        "spec_version": "v1",
        "graph_version": "v1",
        "config_fingerprint": "b" * 64,
        "search_fingerprint": "c" * 64,
        "evidence_snapshot_id": config.snapshot_id,
        "price_table_version": config.price_version,
        "model_provider": "DIGITALOCEAN_HARNESS_INFERENCE",
        "model_id": config.model_id,
        "limits": PROFILE_DEFAULTS[RunProfile.HOSTED_MANUAL],
    }
    result = graph.invoke(state)
    assert result["final_status"] == "FAILED"
    assert statements == [
        "SELECT CURRENT_USER(), CURRENT_ROLE(), CURRENT_DATABASE(), CURRENT_WAREHOUSE()"
    ]
    assert closed == [True]
