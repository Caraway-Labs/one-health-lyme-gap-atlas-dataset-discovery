"""Operator CLI for individually authenticated Dataset Discovery review."""

import argparse
import re
import sys
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from lyme_gap_atlas_dataset_discovery.adapters.snowflake_review import (
    SnowflakeHumanReviewRepository,
)
from lyme_gap_atlas_dataset_discovery.domain.review import ReviewDecision
from lyme_gap_atlas_dataset_discovery.review_service import HumanReviewService

_CONNECTION_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DECISIONS = {
    "accept-for-investigation": ReviewDecision.ACCEPT_FOR_INVESTIGATION,
    "reject": ReviewDecision.REJECT,
    "mark-duplicate": ReviewDecision.MARK_DUPLICATE,
    "mark-already-known": ReviewDecision.MARK_ALREADY_KNOWN,
    "request-more-information": ReviewDecision.REQUEST_MORE_INFORMATION,
    "expire": ReviewDecision.EXPIRE,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dataset-discovery-review")
    parser.add_argument(
        "--connection",
        required=True,
        help="individually authenticated named Snowflake PAT connection",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list pending reviews for one run")
    listing.add_argument("--run-id", required=True)
    listing.add_argument("--after-rank", type=int, default=0)
    listing.add_argument("--limit", type=int, default=25)
    detail = commands.add_parser("show", help="show an exact recommendation version")
    detail.add_argument("recommendation_version_id")
    history = commands.add_parser("history", help="show append-only review events")
    history.add_argument("recommendation_version_id")
    history.add_argument("--after-sequence", type=int, default=0)
    history.add_argument("--limit", type=int, default=50)
    for name in _DECISIONS:
        decision = commands.add_parser(name)
        decision.add_argument("recommendation_version_id")
        decision.add_argument("--rationale", required=True)
        decision.add_argument("--expected-event-id")
        decision.add_argument("--correction-of-event-id")
        decision.add_argument("--condition", action="append", default=[])
    return parser


def _open_connection(name: str) -> Any:
    """Force PAT authentication; do not fall back to browser or OAuth."""
    import snowflake.connector

    return snowflake.connector.connect(
        connection_name=name,
        authenticator="PROGRAMMATIC_ACCESS_TOKEN",
        login_timeout=15,
        network_timeout=30,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not _CONNECTION_NAME.fullmatch(args.connection):
        print("Invalid named connection", file=sys.stderr)
        return 2
    try:
        with _open_connection(args.connection) as connection:
            service = HumanReviewService(SnowflakeHumanReviewRepository(connection))
            result: BaseModel
            if args.command == "list":
                result = service.list_pending(
                    args.run_id, after_rank=args.after_rank, limit=args.limit
                )
            elif args.command == "show":
                result = service.show(args.recommendation_version_id)
            elif args.command == "history":
                result = service.history(
                    args.recommendation_version_id,
                    after_sequence=args.after_sequence,
                    limit=args.limit,
                )
            else:
                result = service.decide(
                    args.recommendation_version_id,
                    _DECISIONS[args.command],
                    rationale=args.rationale,
                    expected_prior_event_id=args.expected_event_id,
                    conditions=tuple(args.condition),
                    correction_of_event_id=args.correction_of_event_id,
                )
        print(result.model_dump_json(indent=2))
        return 0
    except (KeyError, PermissionError, ValueError) as error:
        print(f"Review request refused: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        # Connector errors may include SQL or account context. Never print them verbatim.
        print(f"Review operation failed: {type(error).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
