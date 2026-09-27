"""The versioned corpus must remain an executable graph and receipt gate."""

from pathlib import Path

from lyme_gap_atlas_dataset_discovery.graph_evaluation import (
    TrajectoryCorpus,
    evaluate_case,
    evaluate_corpus,
)


def test_versioned_graph_trajectories_and_replay() -> None:
    corpus = Path(__file__).resolve().parents[1] / "eval/corpora/v1/graph_trajectories.json"
    report = evaluate_corpus(corpus)
    assert report["passed"], report
    assert len(report["cases"]) == 13


def test_trajectory_oracle_rejects_a_wrong_expected_path() -> None:
    corpus = Path(__file__).resolve().parents[1] / "eval/corpora/v1/graph_trajectories.json"
    case = TrajectoryCorpus.model_validate_json(corpus.read_text(encoding="utf-8")).cases[0]
    result = evaluate_case(case.model_copy(update={"nodes": ("initialize_run",)}))
    assert result["passed"] is False
    assert "nodes" in result["failures"]
