# Offline Dataset Discovery contract evaluation v2

Scope: **DETERMINISTIC_FIXTURE**. Semantic quality and hosted acceptance remain **false**.

These reports use synthetic candidates/receipts and an offline transport fixture. No model call, database connection, credential, remote exporter or live write is part of the commands. Passing adverse cases means expected rejection/recovery was observed.

| Corpus | Cases | Result | Input SHA-256 |
| --- | ---: | --- | --- |
| [domain and receipt](../corpora/v2/cases.json) | 27 | PASS | `b90fdebed50675e1cad4f489a3195a7012c2d2b03db87cd54a20416f23687adf` |
| [graph trajectories](../corpora/v2/graph_trajectories.json) | 21 | PASS | `106155151b956df69652d5446ef7b355d8d9905e44bf37762f0313b806096f7d` |
| [handoff governance and recovery](../corpora/v2/handoff.json) | 17 | PASS | `bbfa1969492389572f1fa475957e5d9466d339fda2201234d328462cbc11fc25` |

All fingerprints use UTF-8 text with LF-normalized line endings, so Windows
and Linux checkouts reproduce them.

The source fingerprints below identify the evaluator/trace/test inputs used for this report. The exact reviewed commit and CI evidence belong in the PR; this report makes no deployment claim.

| File | SHA-256 |
| --- | --- |
| [src/lyme_gap_atlas_dataset_discovery/evaluation.py](../../src/lyme_gap_atlas_dataset_discovery/evaluation.py) | `6380edcfe399caa4725559213dcc5985efb3ca7d17fb7bc1805fdb6ac53da52a` |
| [src/lyme_gap_atlas_dataset_discovery/evaluation_fixtures.py](../../src/lyme_gap_atlas_dataset_discovery/evaluation_fixtures.py) | `0ccc649c8963de87b4d5c16af667163d53d89e6d15f94b20b2b6451cbb02a4e2` |
| [src/lyme_gap_atlas_dataset_discovery/graph_evaluation.py](../../src/lyme_gap_atlas_dataset_discovery/graph_evaluation.py) | `5d86cc7f65f6acc721885bb875f52e3260874cf44301ba1a0421fe82f5ccff27` |
| [src/lyme_gap_atlas_dataset_discovery/handoff_evaluation.py](../../src/lyme_gap_atlas_dataset_discovery/handoff_evaluation.py) | `b31083821e97be71cb39a0adf0b2987f8df87d671fec083ab88d6c09c5591a90` |
| [src/lyme_gap_atlas_dataset_discovery/observability.py](../../src/lyme_gap_atlas_dataset_discovery/observability.py) | `de22818c178b35dfa9648c42ce22ba17df92926630800a0b525495a62ee9eafc` |
| [tests/test_offline_evaluation_contracts.py](../../tests/test_offline_evaluation_contracts.py) | `4ea53de176c526d7b12b965e6ecee7b58b485b9f89ae49db5ac1b13c827f3efd` |

Reproduce with the commands in [the evaluation guide](../README.md#offline-contract-corpus-v2). Versioned v1 corpora remain unchanged. The in-memory span tests run as part of `uv run pytest -q`; they do not demonstrate Arize AX delivery.

Required next evidence: independently reviewed labels; merged/exact-head regression gates; real least-privilege DEV recommendation persistence; attributable human review and governed handoff; separately authorized same-input hosted/semantic evaluation and inspected remote trace receipt. A synthetic success cannot substitute for any of those.
