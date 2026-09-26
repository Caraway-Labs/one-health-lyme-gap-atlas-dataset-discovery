"""Deterministic relationship precedence over already-governed identity signals.

Semantic analysis may resolve UNKNOWN, but cannot override a supported exact
identity or a documented source-version relation.
"""

from pydantic import Field, model_validator

from .models import StrictModel
from .ranking import Relationship


class RelationshipSignals(StrictModel):
    candidate_resource_key: str = Field(min_length=1)
    candidate_catalog_dataset_id: str = Field(min_length=1)
    candidate_canonical_url: str | None = None
    known_resource_key: str | None = None
    known_catalog_dataset_id: str | None = None
    known_canonical_url: str | None = None
    known_source_is_governed: bool = False
    same_retained_content_hash: bool = False
    documented_supersedes_known: bool = False
    documented_revision_of_known: bool = False
    supporting_observation_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_link_evidence(self) -> "RelationshipSignals":
        if (
            self.same_retained_content_hash
            or self.documented_supersedes_known
            or self.documented_revision_of_known
        ) and not self.supporting_observation_ids:
            raise ValueError("relationship link requires retained evidence")
        return self


class RelationshipResult(StrictModel):
    relationship: Relationship
    basis: str
    supporting_observation_ids: tuple[str, ...]


def classify_relationship(signals: RelationshipSignals) -> RelationshipResult:
    """Resolve unambiguous relationships without model-generated certainty."""
    same_key = (
        signals.known_resource_key is not None
        and signals.candidate_resource_key == signals.known_resource_key
    )
    same_url = (
        signals.candidate_canonical_url is not None
        and signals.known_canonical_url is not None
        and signals.candidate_canonical_url == signals.known_canonical_url
    )
    same_dataset = (
        signals.known_catalog_dataset_id is not None
        and signals.candidate_catalog_dataset_id == signals.known_catalog_dataset_id
    )

    if same_key and signals.known_source_is_governed:
        relationship, basis = Relationship.ALREADY_KNOWN, "GOVERNED_RESOURCE_KEY"
    elif same_key or same_url:
        relationship, basis = Relationship.EXACT_DUPLICATE, "EXACT_IDENTITY"
    elif signals.documented_supersedes_known:
        relationship, basis = Relationship.SUPERSESSION, "DOCUMENTED_SUPERSESSION"
    elif signals.documented_revision_of_known:
        relationship, basis = Relationship.REVISION, "DOCUMENTED_REVISION"
    elif signals.same_retained_content_hash:
        relationship, basis = Relationship.MIRROR, "SAME_RETAINED_CONTENT"
    elif same_dataset:
        relationship, basis = Relationship.ALTERNATE_DISTRIBUTION, "SAME_CATALOG_DATASET"
    else:
        relationship, basis = Relationship.UNKNOWN, "NO_DETERMINISTIC_LINK"

    return RelationshipResult(
        relationship=relationship,
        basis=basis,
        supporting_observation_ids=signals.supporting_observation_ids,
    )
