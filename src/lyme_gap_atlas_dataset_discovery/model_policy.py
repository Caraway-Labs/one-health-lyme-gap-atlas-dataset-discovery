"""Versioned non-secret model and price policy for the first DEV candidate."""

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from typing import Any


def _load(name: str) -> dict[str, Any]:
    data = json.loads(
        files("lyme_gap_atlas_dataset_discovery").joinpath("config", name).read_text("utf-8")
    )
    if not isinstance(data, dict):
        raise ValueError("model policy must be an object")
    return data


def _fingerprint(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelPolicy:
    document: dict[str, Any]
    fingerprint: str

    @classmethod
    def luna_low_v1(cls) -> "ModelPolicy":
        document = _load("openai-gpt-6-luna-low-v1.json")
        return cls._validated_luna_low(document)

    @classmethod
    def luna_low_v2(cls) -> "ModelPolicy":
        """Current Luna Low policy; only the semantic prompt version differs from v1."""
        document = _load("openai-gpt-6-luna-low-v2.json")
        if document.get("prompt_version") != "dataset-discovery-openai-semantic-v2":
            raise ValueError("semantic prompt version differs from reviewed v2 contract")
        return cls._validated_luna_low(document)

    @classmethod
    def luna_low_v2_4096(cls) -> "ModelPolicy":
        """Reviewed single-candidate DEV experiment with the v2 prompt and 4096 output cap."""
        document = _load("openai-gpt-6-luna-low-v2-4096.json")
        previous = cls.luna_low_v2().document
        if document.get("max_output_tokens_per_call") != 4096 or {
            key: value for key, value in document.items() if key != "max_output_tokens_per_call"
        } != {key: value for key, value in previous.items() if key != "max_output_tokens_per_call"}:
            raise ValueError("4096 experiment differs beyond the reviewed output cap")
        return cls._validated_luna_low(document)

    @classmethod
    def _validated_luna_low(cls, document: dict[str, Any]) -> "ModelPolicy":
        expected = {
            "provider": "openai",
            "model": "gpt-6-luna",
            "api": "responses",
            "reasoning_effort": "low",
            "structured_outputs": True,
            "model_policy_version": "atlas-dd-model-v1",
            "processing_mode": "standard",
            "store": False,
            "tools": [],
        }
        if any(document.get(key) != value for key, value in expected.items()):
            raise ValueError("model policy differs from the approved v1 configuration")
        if set(document["capabilities"].values()) != {False}:
            raise ValueError("model tools must be disabled")
        return cls(document, _fingerprint(document))


@dataclass(frozen=True)
class LunaPriceTable:
    document: dict[str, Any]
    fingerprint: str

    @classmethod
    def standard_v1(cls) -> "LunaPriceTable":
        document = _load("openai-gpt-6-luna-standard-prices-v1.json")
        if (
            document.get("provider") != "openai"
            or document.get("model") != "gpt-6-luna"
            or document.get("processing_mode") != "standard"
            or document.get("long_context_threshold_input_tokens") != 272000
        ):
            raise ValueError("price table identity differs from approved model")
        return cls(document, _fingerprint(document))

    @property
    def version(self) -> str:
        return str(self.document["version"])

    def charge_cents(
        self,
        input_tokens: int,
        output_tokens: int,
        *,
        cached_input_tokens: int = 0,
        cache_write_tokens: int | None = None,
    ) -> int:
        if min(input_tokens, output_tokens, cached_input_tokens) < 0:
            raise ValueError("negative token usage")
        if cached_input_tokens > input_tokens:
            raise ValueError("cached tokens exceed input tokens")
        if cache_write_tokens is not None and not 0 <= cache_write_tokens <= (
            input_tokens - cached_input_tokens
        ):
            raise ValueError("invalid cache write usage")
        band = (
            "long_context_usd_per_million"
            if input_tokens > self.document["long_context_threshold_input_tokens"]
            else "short_context_usd_per_million"
        )
        rates = self.document[band]
        uncached = input_tokens - cached_input_tokens
        # OpenAI does not always report cache writes separately. In that case,
        # charge all uncached input at the higher cache-write rate to bound spend.
        writes = uncached if cache_write_tokens is None else cache_write_tokens
        ordinary = uncached - writes
        dollars = (
            Decimal(ordinary) * Decimal(rates["input"])
            + Decimal(cached_input_tokens) * Decimal(rates["cached_input"])
            + Decimal(writes) * Decimal(rates["cache_write"])
            + Decimal(output_tokens) * Decimal(rates["output"])
        ) / Decimal(1_000_000)
        return math.ceil(dollars * 100)
