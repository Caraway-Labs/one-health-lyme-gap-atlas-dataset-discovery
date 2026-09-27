"""Clear identity signals take precedence; absence of evidence stays unknown."""

import pytest
from pydantic import ValidationError

from lyme_gap_atlas_dataset_discovery.domain.ranking import Relationship
from lyme_gap_atlas_dataset_discovery.domain.relationships import (
    RelationshipSignals,
    classify_relationship,
)


def signals(**changes: object) -> RelationshipSignals:
    values: dict[str, object] = {
        "candidate_resource_key": "candidate",
        "candidate_catalog_dataset_id": "dataset-a",
        "known_resource_key": "known",
        "known_catalog_dataset_id": "dataset-b",
        "supporting_observation_ids": ("observation-1",),
    }
    values.update(changes)
    return RelationshipSignals.model_validate(values)


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        (
            {"known_resource_key": "candidate", "known_source_is_governed": True},
            Relationship.ALREADY_KNOWN,
        ),
        ({"known_resource_key": "candidate"}, Relationship.EXACT_DUPLICATE),
        (
            {
                "candidate_canonical_url": "https://example.org/a",
                "known_canonical_url": "https://example.org/a",
            },
            Relationship.EXACT_DUPLICATE,
        ),
        ({"documented_supersedes_known": True}, Relationship.SUPERSESSION),
        ({"documented_revision_of_known": True}, Relationship.REVISION),
        ({"same_retained_content_hash": True}, Relationship.MIRROR),
        ({"known_catalog_dataset_id": "dataset-a"}, Relationship.ALTERNATE_DISTRIBUTION),
        ({}, Relationship.UNKNOWN),
    ],
)
def test_relationship_precedence(changes: dict[str, object], expected: Relationship) -> None:
    assert classify_relationship(signals(**changes)).relationship == expected


def test_exact_identity_outweighs_documented_revision() -> None:
    result = classify_relationship(
        signals(known_resource_key="candidate", documented_revision_of_known=True)
    )
    assert result.relationship == Relationship.EXACT_DUPLICATE


def test_unsupported_link_is_rejected() -> None:
    with pytest.raises(ValidationError, match="requires retained evidence"):
        signals(same_retained_content_hash=True, supporting_observation_ids=())
