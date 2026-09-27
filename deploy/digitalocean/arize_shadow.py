"""DigitalOcean-only bootstrap for approved Arize AX OTLP headers."""

import os
from collections.abc import MutableMapping


def install_otlp_headers(environment: MutableMapping[str, str]) -> None:
    """Compose a generic exporter setting from two managed secret slots."""
    space_id = environment.pop("ATLAS_DD_DEV_ARIZE_SPACE_ID", "")
    api_key = environment.pop("ATLAS_DD_DEV_ARIZE_API_KEY", "")
    if (
        not space_id
        or not api_key
        or any(character in value for value in (space_id, api_key) for character in ",\r\n")
    ):
        raise ValueError("managed Arize OTLP credential is unavailable or invalid")
    environment["OTEL_EXPORTER_OTLP_HEADERS"] = f"arize-space-id={space_id},arize-api-key={api_key}"


def main() -> int:
    try:
        install_otlp_headers(os.environ)
    except ValueError:
        print("Arize OTLP bootstrap blocked: managed credential unavailable")
        return 1
    from lyme_gap_atlas_dataset_discovery.hosted_shadow import main as shadow_main

    return shadow_main()


if __name__ == "__main__":
    raise SystemExit(main())
