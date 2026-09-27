"""The versioned corpus must remain an executable graph and receipt gate."""

from pathlib import Path

from lyme_gap_atlas_dataset_discovery.graph_evaluation import evaluate_corpus


def test_versioned_graph_trajectories_and_replay() -> None:
    corpus = Path(__file__).resolve().parents[1] / "eval/corpora/v1/graph_trajectories.json"
    report = evaluate_corpus(corpus)
    assert report["passed"], report
    assert len(report["cases"]) >= 6
