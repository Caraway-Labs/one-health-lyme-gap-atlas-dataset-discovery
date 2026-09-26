"""The priority formula is deterministic and evidence-gated."""

import pytest
from pydantic import ValidationError

from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    Dimension,
    PriorityBucket,
    PriorityInput,
    RankingDimensions,
    Relationship,
    rank_candidate,
)


def dimensions(*, relevance: int | None = 2) -> RankingDimensions:
    def item(value: int | None) -> Dimension:
        return Dimension(
            value=value, supporting_observation_ids=("obs-1",) if value is not None else ()
        )

    return RankingDimensions(
        relevance=item(relevance),
        geography=item(2),
        variables=item(2),
        time=item(2),
        provenance=item(2),
        freshness=item(2),
        rights_clarity=item(None),
        complementarity=item(2),
    )


def candidate(relationship: Relationship = Relationship.DISTINCT) -> PriorityInput:
    return PriorityInput(
        resource_key="resource-1",
        recommendation_version_id="version-1",
        observed_evidence_ids=frozenset({"obs-1"}),
        relationship=relationship,
        dimensions=dimensions(),
    )


def test_rank_and_relationship_adjustments() -> None:
    distinct = rank_candidate(candidate())
    complementary = rank_candidate(candidate(Relationship.COMPLEMENTARY))
    mirror = rank_candidate(candidate(Relationship.MIRROR))
    assert distinct.score == 38
    assert distinct.bucket == PriorityBucket.HIGH
    assert complementary.score == 38
    assert distinct.missing_count == 1
    assert mirror.score == 38
    assert mirror.bucket == PriorityBucket.LOW
    assert distinct.sort_key == complementary.sort_key
    assert distinct.sort_key < mirror.sort_key


def test_unknown_relationship_and_missing_dimensions_are_explicit_penalties() -> None:
    unknown = rank_candidate(candidate(Relationship.UNKNOWN))
    assert unknown.relationship_adjustment == -2
    assert unknown.score == 36
    assert unknown.missing_count == 1
    all_known = candidate().model_copy(
        update={
            "dimensions": candidate().dimensions.model_copy(
                update={"rights_clarity": Dimension(value=2, supporting_observation_ids=("obs-1",))}
            )
        }
    )
    assert rank_candidate(all_known).score == 42


def test_unknown_rights_do_not_block_investigation() -> None:
    result = rank_candidate(candidate())
    assert result.score is not None
    assert result.abstain_reason is None


@pytest.mark.parametrize("relation", [Relationship.EXACT_DUPLICATE, Relationship.ALREADY_KNOWN])
def test_known_resource_abstains(relation: Relationship) -> None:
    result = rank_candidate(candidate(relation))
    assert result.bucket == PriorityBucket.ABSTAIN
    assert result.score is None


def test_missing_relevance_abstains() -> None:
    input_value = candidate().model_copy(update={"dimensions": dimensions(relevance=None)})
    assert rank_candidate(input_value).abstain_reason == "INSUFFICIENT_EVIDENCE"


def test_evidence_reference_must_exist() -> None:
    input_value = candidate().model_copy(update={"observed_evidence_ids": frozenset({"other"})})
    with pytest.raises(ValueError, match="unavailable evidence"):
        rank_candidate(input_value)


def test_dimension_cannot_be_scored_without_evidence() -> None:
    with pytest.raises(ValidationError, match="needs evidence"):
        Dimension(value=2)
