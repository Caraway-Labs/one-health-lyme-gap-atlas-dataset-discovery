"""Deployment bootstrap composes OTLP settings without exposing credentials."""

import importlib.util
from pathlib import Path

import pytest
from opentelemetry.sdk.resources import Resource

SCRIPT = Path(__file__).resolve().parents[1] / "deploy/digitalocean/arize_shadow.py"
spec = importlib.util.spec_from_file_location("arize_shadow_bootstrap", SCRIPT)
assert spec is not None and spec.loader is not None
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def test_managed_slots_become_generic_otlp_headers() -> None:
    environment = {
        "ATLAS_DD_DEV_ARIZE_SPACE_ID": "synthetic-space",
        "ATLAS_DD_DEV_ARIZE_API_KEY": "synthetic-key",
    }
    bootstrap.install_otlp_headers(environment)
    assert environment == {
        "OTEL_EXPORTER_OTLP_HEADERS": "arize-space-id=synthetic-space,arize-api-key=synthetic-key"
    }


def test_missing_or_header_delimiter_fails_closed() -> None:
    for key in ("", "bad,value", "bad\nvalue"):
        with pytest.raises(ValueError, match="unavailable or invalid"):
            bootstrap.install_otlp_headers(
                {
                    "ATLAS_DD_DEV_ARIZE_SPACE_ID": "synthetic-space",
                    "ATLAS_DD_DEV_ARIZE_API_KEY": key,
                }
            )


def test_openinference_project_resource_is_loaded_from_generic_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "OTEL_RESOURCE_ATTRIBUTES",
        "openinference.project.name=atlas-dataset-discovery,atlas.environment=DEV,atlas.mode=SHADOW",
    )
    resource = Resource.create({"service.name": "atlas-dataset-discovery"})
    assert resource.attributes["openinference.project.name"] == "atlas-dataset-discovery"
    assert resource.attributes["atlas.environment"] == "DEV"
    assert resource.attributes["atlas.mode"] == "SHADOW"
