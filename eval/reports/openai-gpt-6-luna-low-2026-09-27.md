# GPT-6 Luna low candidate evaluation — DEV, 2026-09-27

Status: **not promoted**. This is a semantic-model evaluation, not a real
Dataset Discovery run, source review, or hosted runtime test.

## Exact configuration

- Provider/model/API: OpenAI `gpt-6-luna`, Responses API, Standard processing.
- Reasoning: `low`; strict typed structured output; `tools=[]`; `store=false`.
- Policy: `atlas-dd-model-v1`, prompt `dataset-discovery-openai-semantic-v1`.
- Model configuration fingerprint:
  `20f0f248f862ef2ebdcd9b1aa4f7d6decb9b8a2384dc79188081055bfbe1a38f`.
- Price table: `openai-gpt-6-luna-standard-2026-09-27-v1`, fingerprint
  `33b9b96045b3b5645c3f11673de1ea942511547f4a9e7d85fa161488038fe0a5`.
- Corpus: `dataset-discovery-domain-v1`, 11 synthetic cases. Credential was read
  from a local file outside the repository and was never included in this report.

## Observed result

| Measure | Result |
| --- | ---: |
| Cases | 11 |
| Structured responses passing Atlas evidence/dimension checks | 11 |
| Schema-invalid or incomplete responses | 0 |
| Comparable priority buckets matching corpus | 1 of 9 |
| Input tokens | 13,354 |
| Cached input tokens | 13,321 |
| Output tokens | 7,598 |
| Reasoning tokens | 1,020 |
| Mean / median / p95 latency | 5.54 / 5.27 / 8.61 seconds |
| Conservative rounded charge | 11 cents |

All eleven calls returned metered usage. Each rounded up to one cent under the
conservative cache-write assumption, for an 11-cent bounded-run estimate. No
unauthorized operation, reviewer attribution, rights clearance, approval,
ingestion, or handoff occurred; this runner has no such capabilities. The
prompt-injection case passed Atlas evidence validation, but the model abstained.

The model classified all eleven cases as `INSUFFICIENT_EVIDENCE`, including
cases whose reviewed corpus expects a useful recommendation. An earlier runner
mistakenly capped output at 1,024 tokens and produced one invalid result; that
report is superseded. This report used the exact 2,048-token model policy,
eliminated the schema failure, and still failed the semantic-quality gate.

## Decision required before live DEV recommendation

Keep `gpt-6-luna`/low as the initial candidate configuration, with scheduling
disabled. Compare a new, separately fingerprinted prompt/evidence-packaging
variant against this baseline, and consider an explicit Luna-medium comparison
only with owner approval. Preserve the zero-tolerance governance gates and
require a satisfactory semantic-quality baseline before a real recommendation,
human review, handoff, or hosted deployment.
