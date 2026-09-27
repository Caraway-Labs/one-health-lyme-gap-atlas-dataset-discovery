"""Read-only, profile-specific gate for a manually triggered SHADOW session."""

import argparse
import json
from pathlib import Path

from preflight import ROOT, PreflightError, preflight


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Dataset Discovery SHADOW preflight")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--account-uuid", required=True)
    parser.add_argument(
        "--template", type=Path, default=ROOT / "deploy/digitalocean/langgraph-shadow.template.json"
    )
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                preflight(args.sha, args.account_uuid, args.template, profile="SHADOW"), indent=2
            )
        )
        return 0
    except (PreflightError, OSError, ValueError) as error:
        print(f"Shadow preflight blocked: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
