"""Read-only, profile-specific gate for a manually triggered SHADOW session."""

import argparse
import json
from pathlib import Path

from preflight import ROOT, PreflightError, offline_preflight, preflight


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Dataset Discovery SHADOW preflight")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--account-uuid")
    parser.add_argument("--offline", action="store_true", help="local nonsecret checks only")
    parser.add_argument(
        "--template", type=Path, default=ROOT / "deploy/digitalocean/langgraph-shadow.template.json"
    )
    args = parser.parse_args()
    try:
        if args.offline:
            report = offline_preflight(args.sha, args.template, profile="SHADOW")
        else:
            if args.account_uuid is None:
                raise PreflightError("credentialed preflight requires intended account UUID")
            report = preflight(args.sha, args.account_uuid, args.template, profile="SHADOW")
        print(json.dumps(report, indent=2))
        return 0
    except PreflightError as error:
        print(f"Shadow preflight blocked: {error}")
        return 1
    except (OSError, ValueError):
        print("Shadow preflight blocked: invalid or unavailable configuration")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
