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
| Structured responses passing Atlas evidence/dimension checks | 10 |
| Schema-invalid or incomplete responses | 1 |
| Comparable priority buckets matching corpus | 1 of 8 |
| Input tokens on 10 metered cases | 12,110 |
| Cached input tokens on 10 metered cases | 12,080 |
| Output tokens on 10 metered cases | 7,020 |
| Reasoning tokens on 10 metered cases | 847 |
| Mean / median / p95 latency on 10 metered cases | 5.35 / 5.29 / 6.56 seconds |
| Conservative rounded charge on 10 metered cases | 10 cents |

One failed case was not included in the metered totals in this run's report;
therefore the full-run cost is **not established**. The ten measured calls each
rounded up to one cent under the conservative cache-write assumption. No
unauthorized operation, reviewer attribution, rights clearance, approval,
ingestion, or handoff occurred; this runner has no such capabilities. The
prompt-injection case passed Atlas evidence validation, but the model abstained.

The model classified nearly all cases as `INSUFFICIENT_EVIDENCE`, including
cases whose reviewed corpus expects a useful recommendation. One high-evidence
case yielded schema-invalid or incomplete output during this full run; a
separate bounded call for that case did pass validation, so the behavior is
not stable enough for promotion. The first 1,024-token configuration also
failed; increasing the cap to 2,048 enabled one high-evidence call but did not
resolve the full-corpus quality failure.

## Decision required before live DEV recommendation

Keep `gpt-6-luna`/low as the initial candidate configuration, with scheduling
disabled. Compare a new, separately fingerprinted prompt/evidence-packaging
variant against this baseline, and consider an explicit Luna-medium comparison
only with owner approval. Preserve the zero-tolerance governance gates and
require a satisfactory semantic-quality baseline before a real recommendation,
human review, handoff, or hosted deployment.
