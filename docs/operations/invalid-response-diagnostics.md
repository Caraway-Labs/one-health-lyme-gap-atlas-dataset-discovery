# Invalid semantic response diagnostics (DEV v1)

The provider adapter is `OpenAIResponsesPlanner._invoke` in
`adapters/openai_responses.py`. It requests a strict Pydantic schema for each
relationship, classification, rationale, or proposal task. `CandidateAnalysis`
and `RankingDimensions` are the classification models; the other task output
models are private to the adapter. A completed, metered response can become
`InvalidModelResponse` when its status is not `completed`, its output text is
missing or too large, or `model_validate_json` rejects its JSON/schema.
Pydantic error *type* and bounded field path determine the safe code; error
messages, offending input, and response text are discarded. A metered response
with the wrong model ID is `UnmeteredModelResponse` and stops the run.

`BoundedModelPlanner` converts the provider's parsed object to the typed domain
result. Its shape/type/length checks can also raise `InvalidModelResponse` with
`SEMANTIC_PARSE` and a stable code. `ValidatedCandidatePlanner` then checks
relationship authority and citation IDs, canonical candidate identity,
`validate_analysis` observed facts/inferences/claims/proposals, and
`validate_dimension_evidence`. These failures use `EVIDENCE_VALIDATION`,
`RATIONALE_VALIDATION`, or `PROPOSAL_VALIDATION` with a code mapped from the
validator's fixed error strings. Unknown fixed errors become
`OTHER_VALIDATION_FAILURE`. No untrusted error string enters Snowflake.

Previously, `graph.sequential.guard` normalized all these failures to
`CANDIDATE_ANALYSIS_ERROR`, while `record_candidate_outcome` derived `task_type`
from `current_analysis is not None`. A classification response rejected before
that state field was set therefore appeared as `NOT_CALLED`. The forward DEV
decision record now carries the provider attempt, transport/parse outcomes,
stage, code, safe field path, validator/version, reported usage when available,
schema version, and SHA-256 of a bounded response. When typed output exists
before evidence rejection, it retains only classification, dimension values,
observation IDs, relationship, and unknown field identifiers. It never retains
the raw prompt/response, observed values, reasoning, headers, or credentials.

The receipt's `run_id` and `resource_key` are the run and candidate identities.
`model_call_attempted` means the provider call was issued. A transport failure
has attempted=true, transport=false, parse=false. A schema failure has
attempted=true, transport=true, parse=false. An evidence failure has all three
true and a validator code. Retry attempts are included in run budget counters;
the outcome record describes the final attempt. V121 changes only the existing
candidate-outcome procedure's safe allowlist and checks. The outcome and audit
still commit together under the same operation key and serialized transaction.
