"""Hosted DEV manual composition; imports and graph compilation do not connect."""

import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from lyme_gap_atlas_dataset_discovery.adapters.model_planner import ReviewedModelPrice
from lyme_gap_atlas_dataset_discovery.adapters.openai_responses import OpenAIResponsesPlanner
from lyme_gap_atlas_dataset_discovery.adapters.snowflake_reader import (
    SnowflakeCandidateReader,
    SnowflakeDiscoveryContextReader,
)
from lyme_gap_atlas_dataset_discovery.adapters.snowflake_repository import (
    SnowflakeRecommendationRepository,
)
from lyme_gap_atlas_dataset_discovery.model_policy import LunaPriceTable, ModelPolicy

from .budgets import RunProfile
from .sequential import GraphDependencies, PolicyViolation, build_graph

_SHA = re.compile(r"^[0-9a-f]{40}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


@dataclass(frozen=True)
class HostedConfig:
    profile: RunProfile
    code_sha: str
    snapshot_id: str
    search_fingerprint: str
    price_version: str
    inference_endpoint: str
    model_id: str
    model_api_key: str = field(repr=False)
    model_fingerprint: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    snowflake_account: str
    snowflake_user: str
    snowflake_role: str
    snowflake_database: str
    snowflake_warehouse: str
    snowflake_pat: str = field(repr=False)

    @classmethod
    def from_environment(cls, values: Mapping[str, str] | None = None) -> "HostedConfig":
        env = os.environ if values is None else values
        required = (
            "FRAMEWORK_REPO_SHA",
            "ATLAS_DISCOVERY_SNAPSHOT_ID",
            "ATLAS_DISCOVERY_SEARCH_FINGERPRINT",
            "ATLAS_PRICE_TABLE_VERSION",
            "ATLAS_MODEL_CONFIG_FINGERPRINT",
            "ATLAS_MODEL_PROVIDER",
            "ATLAS_MODEL_ID",
            "ATLAS_MODEL_API",
            "ATLAS_MODEL_REASONING_EFFORT",
            "ATLAS_MODEL_POLICY_VERSION",
            "ATLAS_DD_DEV_OPENAI_API_KEY",
            "SNOWFLAKE_ACCOUNT",
            "SNOWFLAKE_USER",
            "SNOWFLAKE_ROLE",
            "SNOWFLAKE_DATABASE",
            "SNOWFLAKE_WAREHOUSE",
            "ATLAS_DD_DEV_SNOWFLAKE_PAT",
        )
        try:
            profile = RunProfile(env.get("ATLAS_DISCOVERY_PROFILE", ""))
        except ValueError:
            raise ValueError("hosted entrypoint requires a reviewed profile") from None
        if profile not in {RunProfile.HOSTED_MANUAL, RunProfile.SHADOW}:
            raise ValueError("hosted entrypoint requires HOSTED_MANUAL or SHADOW profile")
        if any(not env.get(name) for name in required):
            raise ValueError("hosted entrypoint is missing required managed configuration")
        policy = ModelPolicy.luna_low_v1()
        price_table = LunaPriceTable.standard_v1()
        if (
            env["ATLAS_MODEL_CONFIG_FINGERPRINT"] != policy.fingerprint
            or env["ATLAS_PRICE_TABLE_VERSION"] != price_table.version
            or env["ATLAS_MODEL_PROVIDER"] != "openai"
            or env["ATLAS_MODEL_ID"] != "gpt-6-luna"
            or env["ATLAS_MODEL_API"] != "responses"
            or env["ATLAS_MODEL_REASONING_EFFORT"] != "low"
            or env["ATLAS_MODEL_POLICY_VERSION"] != "atlas-dd-model-v1"
        ):
            raise ValueError("hosted model configuration differs from reviewed source policy")
        try:
            config = cls(
                profile=profile,
                code_sha=env["FRAMEWORK_REPO_SHA"],
                snapshot_id=env["ATLAS_DISCOVERY_SNAPSHOT_ID"],
                search_fingerprint=env["ATLAS_DISCOVERY_SEARCH_FINGERPRINT"],
                price_version=env["ATLAS_PRICE_TABLE_VERSION"],
                inference_endpoint="https://api.openai.com/v1",
                model_id=str(policy.document["model"]),
                model_api_key=env["ATLAS_DD_DEV_OPENAI_API_KEY"],
                model_fingerprint=policy.fingerprint,
                input_usd_per_million=Decimal(
                    price_table.document["short_context_usd_per_million"]["input"]
                ),
                output_usd_per_million=Decimal(
                    price_table.document["short_context_usd_per_million"]["output"]
                ),
                snowflake_account=env["SNOWFLAKE_ACCOUNT"],
                snowflake_user=env["SNOWFLAKE_USER"],
                snowflake_role=env["SNOWFLAKE_ROLE"],
                snowflake_database=env["SNOWFLAKE_DATABASE"],
                snowflake_warehouse=env["SNOWFLAKE_WAREHOUSE"],
                snowflake_pat=env["ATLAS_DD_DEV_SNOWFLAKE_PAT"],
            )
        except InvalidOperation:
            raise ValueError("reviewed model prices must be decimal numbers") from None
        if not _SHA.fullmatch(config.code_sha):
            raise ValueError("hosted graph requires exact deployed commit SHA")
        if not config.snapshot_id or len(config.snapshot_id) > 200:
            raise ValueError("invalid pinned discovery snapshot")
        if not _FINGERPRINT.fullmatch(config.search_fingerprint):
            raise ValueError("invalid pinned discovery search fingerprint")
        if config.snowflake_role != "OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME":
            raise ValueError("first hosted rollout requires dedicated DEV runtime role")
        if config.snowflake_database != "ONE_HEALTH_LYME_GAP_ATLAS_DEV":
            raise ValueError("first hosted rollout requires DEV database")
        if any(
            not _IDENTIFIER.fullmatch(value)
            for value in (config.snowflake_user, config.snowflake_warehouse)
        ):
            raise ValueError("invalid runtime principal or warehouse")
        ReviewedModelPrice(
            config.price_version,
            config.model_id,
            config.input_usd_per_million,
            config.output_usd_per_million,
        )
        return config


class _VerifiedLease:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def __enter__(self) -> "_VerifiedLease":
        return self

    def __exit__(self, *_args: object) -> None:
        self.connection.close()

    def cursor(self) -> Any:
        return self.connection.cursor()


class _LeasedCursor:
    def __init__(self, lease: _VerifiedLease) -> None:
        self._lease = lease
        self._cursor = lease.cursor()

    def execute(
        self, sql: str, params: Sequence[object] = (), *, timeout: int | None = None
    ) -> Any:
        return self._cursor.execute(sql, params, timeout=timeout)

    def fetchone(self) -> Any:
        return self._cursor.fetchone()

    def close(self) -> None:
        try:
            self._cursor.close()
        finally:
            self._lease.connection.close()


class _PerOperationConnection:
    def __init__(self, connect: Callable[[], _VerifiedLease]) -> None:
        self._connect = connect

    def cursor(self) -> _LeasedCursor:
        return _LeasedCursor(self._connect())


def _snowflake_connect(config: HostedConfig) -> Any:
    import snowflake.connector

    # Snowflake documents PAT use as the connector password value. The secret
    # is only supplied by the managed runtime; no interactive auth fallback.
    return snowflake.connector.connect(
        account=config.snowflake_account,
        user=config.snowflake_user,
        password=config.snowflake_pat,
        role=config.snowflake_role,
        database=config.snowflake_database,
        warehouse=config.snowflake_warehouse,
        schema="DATASET_DISCOVERY",
        login_timeout=15,
        network_timeout=30,
        client_session_keep_alive=False,
    )


def build_hosted_graph(
    config: HostedConfig,
    *,
    raw_connect: Callable[[HostedConfig], Any] = _snowflake_connect,
) -> Any:
    """Wire real sequential nodes; verify Snowflake identity before every operation."""
    price = ReviewedModelPrice(
        config.price_version,
        config.model_id,
        config.input_usd_per_million,
        config.output_usd_per_million,
    )
    planner = OpenAIResponsesPlanner(
        config.inference_endpoint,
        config.model_id,
        config.model_api_key,
        price,
        policy=ModelPolicy.luna_low_v1(),
        price_table=LunaPriceTable.standard_v1(),
    )

    def verified_connect() -> _VerifiedLease:
        connection = raw_connect(config)
        try:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "SELECT CURRENT_USER(), CURRENT_ROLE(), "
                    "CURRENT_DATABASE(), CURRENT_WAREHOUSE()",
                    timeout=15,
                )
                row = cursor.fetchone()
                if (
                    row
                    != (
                        config.snowflake_user,
                        config.snowflake_role,
                        config.snowflake_database,
                        config.snowflake_warehouse,
                    )
                    or cursor.fetchone() is not None
                ):
                    raise PolicyViolation(
                        "Snowflake runtime principal or context differs from deployment"
                    )
            finally:
                cursor.close()
        except Exception:
            connection.close()
            raise
        return _VerifiedLease(connection)

    return build_graph(
        GraphDependencies(
            reader=SnowflakeCandidateReader(
                discovery_run_id=config.snapshot_id, connect=verified_connect
            ),
            context_reader=SnowflakeDiscoveryContextReader(connect=verified_connect),
            repository=SnowflakeRecommendationRepository(_PerOperationConnection(verified_connect)),
            planner=planner,
            deployed_code_sha=config.code_sha,
            expected_snapshot_id=config.snapshot_id,
            approved_price_table_version=config.price_version,
            required_profile=config.profile,
            expected_model_id=config.model_id,
            expected_model_provider="OPENAI",
            expected_model_fingerprint=config.model_fingerprint,
        )
    )
