"""General investigation semantics, independent of any particular source."""

from lyme_gap_atlas_dataset_discovery.adapters.openai_responses import (
    _SYSTEM,
    _TASK_INSTRUCTIONS,
    OPENAI_PROMPT_VERSION,
)
from lyme_gap_atlas_dataset_discovery.domain.analysis import (
    AvailableObservation,
    CandidateAnalysis,
    Classification,
    validate_analysis,
)
from lyme_gap_atlas_dataset_discovery.domain.models import (
    CandidateIdentity,
    EvidenceRef,
    ObservedFact,
)
from lyme_gap_atlas_dataset_discovery.domain.persistence import (
    RightsEvidenceState,
    rights_evidence_state,
)
from lyme_gap_atlas_dataset_discovery.domain.ranking import (
    Dimension,
    PriorityBucket,
    PriorityInput,
    RankingDimensions,
    Relationship,
    rank_candidate,
)
from lyme_gap_atlas_dataset_discovery.graph.planner import validate_dimension_evidence
from lyme_gap_atlas_dataset_discovery.model_policy import ModelPolicy


def _case(
    description: str,
    *,
    relevance: int | None,
    relationship: Relationship = Relationship.DISTINCT,
    evidence_sufficient: bool = True,
) -> tuple[CandidateAnalysis, RankingDimensions, PriorityInput]:
    identity = CandidateIdentity(
        resource_key="generic-resource",
        catalog_dataset_id="generic-dataset",
        catalog_resource_id="generic-distribution",
    )
    ref = EvidenceRef(
        observation_id="retained-observation",
        catalog_dataset_id=identity.catalog_dataset_id,
        catalog_resource_id=identity.catalog_resource_id,
        observed_at="2026-01-01T00:00:00Z",
    )
    observation = AvailableObservation(reference=ref, field_values={"description": description})
    analysis = CandidateAnalysis(
        identity=identity,
        classification=Classification.RELEVANT
        if relevance is not None
        else Classification.INSUFFICIENT_EVIDENCE,
        observed_facts=(ObservedFact(field="description", value=description, evidence=ref),),
    )
    dimensions = RankingDimensions(
        relevance=Dimension(
            value=relevance,
            supporting_observation_ids=(ref.observation_id,) if relevance is not None else (),
        ),
        geography=Dimension(),
        variables=Dimension(),
        time=Dimension(),
        provenance=Dimension(),
        freshness=Dimension(),
        rights_clarity=Dimension(),
        complementarity=Dimension(),
    )
    validate_analysis(analysis, available_evidence=(observation,))
    validate_dimension_evidence(analysis, dimensions)
    ranked = PriorityInput(
        resource_key=identity.resource_key,
        recommendation_version_id="version-1",
        observed_evidence_ids=frozenset({ref.observation_id}),
        relationship=relationship,
        dimensions=dimensions,
        evidence_sufficient=evidence_sufficient,
    )
    return analysis, dimensions, ranked


def test_prompt_version_and_investigation_rubric() -> None:
    policy = ModelPolicy.luna_low_v2()
    previous = ModelPolicy.luna_low_v1()
    task = _SYSTEM + _TASK_INSTRUCTIONS["classify candidate"]
    assert policy.document["prompt_version"] == OPENAI_PROMPT_VERSION
    assert policy.fingerprint != previous.fingerprint
    assert {k: v for k, v in policy.document.items() if k != "prompt_version"} == {
        k: v for k, v in previous.document.items() if k != "prompt_version"
    }
    assert policy.document["model"] == previous.document["model"] == "gpt-6-luna"
    assert policy.document["reasoning_effort"] == previous.document["reasoning_effort"] == "low"
    assert (
        policy.document["max_output_tokens_per_call"]
        == previous.document["max_output_tokens_per_call"]
        == 2048
    )
    assert "human should investigate" in task
    assert "retained title, description, or keyword can support relevance" in task
    assert "Leave each unsupported optional dimension null" in task
    assert "INSUFFICIENT_EVIDENCE only when retained evidence cannot support" in task


def test_4096_experiment_changes_only_the_model_output_cap() -> None:
    baseline = ModelPolicy.luna_low_v2()
    experiment = ModelPolicy.luna_low_v2_4096()
    assert experiment.document["prompt_version"] == OPENAI_PROMPT_VERSION
    assert experiment.document["max_output_tokens_per_call"] == 4096
    assert baseline.document["max_output_tokens_per_call"] == 2048
    assert {k: v for k, v in experiment.document.items() if k != "max_output_tokens_per_call"} == {
        k: v for k, v in baseline.document.items() if k != "max_output_tokens_per_call"
    }
    assert experiment.fingerprint != baseline.fingerprint


def test_direct_tick_dataset_can_be_low_priority_with_unknown_options() -> None:
    _, dimensions, candidate = _case(
        "Dataset of tickborne pathogen observations over several years", relevance=2
    )
    priority = rank_candidate(candidate)
    assert priority.bucket == PriorityBucket.LOW
    assert priority.score == 0
    assert priority.abstain_reason is None
    assert all(
        dimension.value is None
        for name, dimension in dimensions.__dict__.items()
        if name != "relevance"
    )


def test_generic_description_without_atlas_relevance_abstains() -> None:
    _, _, candidate = _case("Generic administrative records", relevance=None)
    priority = rank_candidate(candidate)
    assert priority.bucket == PriorityBucket.ABSTAIN
    assert priority.abstain_reason == "INSUFFICIENT_EVIDENCE"


def test_review_article_without_dataset_resource_evidence_can_abstain() -> None:
    _, _, candidate = _case(
        "Review article about Lyme disease, with no dataset or distribution",
        relevance=2,
        evidence_sufficient=False,
    )
    assert rank_candidate(candidate).bucket == PriorityBucket.ABSTAIN


def test_rights_unknown_does_not_block_relevant_dataset_investigation() -> None:
    analysis, dimensions, candidate = _case("Dataset of blacklegged tick observations", relevance=2)
    assert rights_evidence_state(analysis) == RightsEvidenceState.RIGHTS_UNKNOWN
    assert dimensions.rights_clarity.value is None
    assert rank_candidate(candidate).bucket == PriorityBucket.LOW


def test_alternate_distribution_is_capped_at_low_when_relevant() -> None:
    _, _, candidate = _case(
        "Dataset of Lyme disease vectors",
        relevance=2,
        relationship=Relationship.ALTERNATE_DISTRIBUTION,
    )
    priority = rank_candidate(candidate)
    assert priority.bucket == PriorityBucket.LOW
    assert priority.abstain_reason is None
