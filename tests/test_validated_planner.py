"""Semantic outputs cannot create source facts or governed relationships."""

import pytest

from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    AvailableObservation,
    CandidateAnalysis,
    Classification,
    RationaleClaim,
)
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    CandidateSummary,
    EvidenceRef,
    ObservedFact,
)
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    Dimension,
    RankingDimensions,
    Relationship,
)
from lyme_gap_atlas_dataset_discovery.domain.relationships import RelationshipResult
from lyme_gap_atlas_dataset_discovery.graph.planner import (
    FakeCandidatePlanner,
    FixturePlan,
    ModelAllowance,
    ValidatedCandidatePlanner,
)


def specimen() -> tuple[CandidateSummary, tuple[AvailableObservation, ...], FixturePlan]:
    identity = CandidateIdentity(
        resource_key="resource", catalog_dataset_id="dataset", catalog_resource_id="item"
    )
    ref = EvidenceRef(
        observation_id="obs-1",
        catalog_dataset_id="dataset",
        catalog_resource_id="item",
        observed_at="2026-09-26T00:00:00Z",
    )
    candidate = CandidateSummary(identity=identity, evidence_refs=(ref,))
    observations = (AvailableObservation(reference=ref, field_values={"publisher": "Agency"}),)
    analysis = CandidateAnalysis(
        identity=identity,
        classification=Classification.RELEVANT,
        observed_facts=(ObservedFact(field="publisher", value="Agency", evidence=ref),),
    )
    unknown = Dimension(value=None)
    dimensions = RankingDimensions(
        relevance=Dimension(value=2, supporting_observation_ids=("obs-1",)),
        geography=unknown,
        variables=unknown,
        time=unknown,
        provenance=unknown,
        freshness=unknown,
        rights_clarity=unknown,
        complementarity=unknown,
    )
    plan = FixturePlan(
        relationship=RelationshipResult(
            relationship=Relationship.COMPLEMENTARY,
            basis="model text is untrusted",
            supporting_observation_ids=("obs-1",),
        ),
        analysis=analysis,
        dimensions=dimensions,
    )
    return candidate, observations, plan


ALLOWANCE = ModelAllowance(
    max_input_tokens=1000, max_output_tokens=1000, max_estimated_spend_cents=10
)


def test_validated_planner_preserves_evidence_and_normalizes_semantic_basis() -> None:
    candidate, observations, plan = specimen()
    planner = ValidatedCandidatePlanner(FakeCandidatePlanner({"resource": plan}))
    relationship = planner.relationship(candidate, observations, allowance=ALLOWANCE)
    assert relationship.value.basis == "SEMANTIC_INFERENCE"
    assert planner.classify(candidate, observations, allowance=ALLOWANCE).value[0] == plan.analysis


def test_semantic_model_cannot_assert_exact_duplicate_or_fabricate_fact() -> None:
    candidate, observations, plan = specimen()
    exact = plan.relationship.model_copy(update={"relationship": Relationship.EXACT_DUPLICATE})
    planner = ValidatedCandidatePlanner(
        FakeCandidatePlanner({"resource": FixturePlan(**{**plan.__dict__, "relationship": exact})})
    )
    with pytest.raises(ValueError, match="cannot assert"):
        planner.relationship(candidate, observations, allowance=ALLOWANCE)

    false_fact = plan.analysis.model_copy(
        update={
            "observed_facts": (
                ObservedFact(
                    field="publisher", value="Invented Agency", evidence=observations[0].reference
                ),
            )
        }
    )
    planner = ValidatedCandidatePlanner(
        FakeCandidatePlanner({"resource": FixturePlan(**{**plan.__dict__, "analysis": false_fact})})
    )
    with pytest.raises(ValueError, match="differs from retained metadata"):
        planner.classify(candidate, observations, allowance=ALLOWANCE)


def test_semantic_rationale_must_match_validated_observation() -> None:
    candidate, observations, plan = specimen()
    fake = FakeCandidatePlanner(
        {
            "resource": FixturePlan(
                **{
                    **plan.__dict__,
                    "rationale": (
                        RationaleClaim(
                            field="publisher",
                            text="Wrong publisher",
                            kind="OBSERVED",
                            supporting_observation_ids=("obs-1",),
                        ),
                    ),
                }
            )
        }
    )
    planner = ValidatedCandidatePlanner(fake)
    with pytest.raises(ValueError, match="differs from validated fact"):
        planner.rationale(plan.analysis, observations, allowance=ALLOWANCE)
