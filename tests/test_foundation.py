from lyme_gap_atlas_dataset_discovery.graph.entrypoint import graph


def test_compiled_graph_needs_no_external_service() -> None:
    assert graph.invoke({"fixture_id": "known"}) == {
        "fixture_id": "known",
        "status": "FOUNDATION_READY",
    }
