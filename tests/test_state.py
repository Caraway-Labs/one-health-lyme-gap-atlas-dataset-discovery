"""Candidate state is reset between sequential iterations."""

from lyme_gap_atlas_dataset_discovery.graph.state import STATE_VERSION, clear_candidate_state


def test_versioned_state_and_candidate_reset() -> None:
    assert STATE_VERSION == "dataset-discovery-state-v1"
    cleared = clear_candidate_state()
    assert cleared["current_candidate_id"] is None
    assert cleared["current_evidence"] == ()
    assert cleared["current_relationship"] is None
    assert cleared["current_analysis"] is None
    assert cleared["current_priority"] is None
    assert cleared["current_proposals"] == ()
    assert cleared["persistence_operation_key"] is None
