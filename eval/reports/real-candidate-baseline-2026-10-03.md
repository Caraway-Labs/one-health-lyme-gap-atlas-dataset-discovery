# Issue #8 current implementation: blocked real-candidate baseline

Date: 2026-10-03. Application SHA: `ec07fe66bbcdd338c8a56eb317df3db5b45130af`. Dedicated branch: `codex/dd8-product-baseline-20261003`.

## Identity and method

This is a **read-only human evidence audit**, not an agent semantic evaluation. The current supported local DEV runner could not execute: its dedicated `ATLAS_DD_DEV_OPENAI_API_KEY`, pinned execution configuration, and owner-reviewed cost evidence were absent. The runner's documented limit is one candidate per invocation. No model call, recommendation write, prompt change, ranking change, or permission change was made. Therefore all 25 rows below have **agent semantic classification, agent relationship decision, eligibility, score/priority, recommendation, stop reason, and agent rationale = NOT EVALUATED**. The human judgments are provisional and cannot be counted as application outputs.

The governed candidate source is completed DEV discovery run `0e886e34-2166-4eb6-8013-f57d2c0c9337` (107 resource entries, search fingerprint `f417ff3147ec73eb759a57c7ea47fff325f9a56bfcaa8de1628d41f3d164acdb`, completed 2026-08-24). Current safe observation fields were observed 2026-09-27, so this is **not a proven immutable 2026-08-24 evidence snapshot**. The newer contexts through 2026-09-28 are `PAUSED` and yielded no rows in `V_CANDIDATE_SUMMARY` to the runtime role. Source: `DATASET_DISCOVERY.V_DISCOVERY_CONTEXT`, `V_CANDIDATE_SUMMARY`, `V_CANDIDATE_OBSERVATION_FIELDS`, `V_CANDIDATE_GOVERNED_STATUS`, and `V_CANDIDATE_IDENTITY_LINKS`, read through the existing `ATLAS_DEV_DATASET_DISCOVERY_RUNTIME` profile. Identity preflight returned service user `OH_LYME_DEV_DATASET_DISCOVERY_SVC`, role `OH_LYME_DEV_DATASET_DISCOVERY_RUNTIME`, DEV database and `OH_LYME_DEV_INGEST_XS_WH`.

Current model policy is `gpt-6-luna`, low, Responses API, semantic prompt `dataset-discovery-openai-semantic-v2`, standard 2048 output-token profile fingerprint `91e7ce172816efc88dd8568bd75996048caa773e87310a6c5c135019a71662b2`; the reviewed SHADOW 4096 variant fingerprint is `e9555669d603689171a22718f4b44adf26322774a632b20cd0ec90d19700017f`. Price-table fingerprint is `33b9b96045b3b5645c3f11673de1ea942511547f4a9e7d85fa161488038fe0a5`. Neither model profile was executed here. The exact run-time snapshot/config for a new run is consequently unavailable.

## Candidate-level human audit

All listed IDs are full stable resource keys under the run above. `ALT(n)` means the governed identity-link view reports `ALTERNATE_DISTRIBUTION` with n links; `none` means no row from that view. `already_governed=false` for all 25. These are observed relationship inputs, not final agent relationship outputs. All rows have `spatial=NULL`; observed geography in a title or description is not a structured coverage field. `UNKNOWN` includes Lyme-specific variables, usable county resolution, rights interpretation, or temporal coverage unless stated. Human judgment is whether a steward might investigate, not source approval.

| Candidate ID | Safe title / resource | Human provisional view | Observed evidence and relationship | Important UNKNOWN / likely failure |
| --- | --- | --- | --- | --- |
| `candidate:2cb43d43a57dc1ae77172b02fd8cc0f1` | CA Hospital Inpatient by Patient County; MDC file | Plausibly useful context | Public CSV; description names county, MDC and diagnosis groups; CC-BY metadata; ALT(9) | Lyme-specific diagnoses and usable county detail unverified; other resources share parent |
| `candidate:5efec5c06bfd8c92f767157d261870b3` | Same CA dataset; sex file | Weak standalone value | Public CSV; county summary description; ALT(9) | Lyme relevance and value beyond MDC file unverified |
| `candidate:6dd8ab3b1061ddbaba34c879c5d94e86` | Same CA dataset; type-of-care file | Weak standalone value | Public CSV; county summary description; ALT(9) | Lyme relevance and complementary benefit unverified |
| `candidate:a3e84dcdba743fe4438d598d7ae7a03a` | Same CA dataset; payer file | Weak standalone value | Public CSV; county summary description; ALT(9) | Lyme relevance and complementary benefit unverified |
| `candidate:d0251cf830694628587423730474c8b3` | Same CA dataset; race-group file | Weak standalone value | Public CSV; county summary description; ALT(9) | Lyme relevance and complementary benefit unverified |
| `candidate:142b7c96d7b2b0b8b1af6110c55f2fd2` | CT School Learning Indicators, 7-day archive | Irrelevant to Lyme discovery | Public DATA; COVID archive keyword; ALT(3) | Description, rights detail, coverage absent; title points away from Lyme |
| `candidate:4fba3285278826416ed8aa796c64ced3` | CT School Learning Indicators, 14-day archive | Irrelevant | Public DATA; archive title; ALT(3) | Description and structured coverage absent |
| `candidate:5b6e1283b17469e7b0c12d45907d6edb` | CT School Learning Indicators, 7-day landing page | Irrelevant alternate | Public landing page; same catalog identity; ALT(3) | Description and separate benefit absent |
| `candidate:726eec960d615570000923a7254d96d1` | CT School Learning Indicators, 14-day landing page | Irrelevant alternate | Public landing page; same catalog identity; ALT(3) | Description and separate benefit absent |
| `candidate:9647ef1591b2f0a3d288ea6b0124f2b9` | CT School Learning Indicators, 7-day archive | Irrelevant alternate | Public DATA; same catalog identity; ALT(3) | Description and separate benefit absent |
| `candidate:010d06b22d1f40629c8eb50a6bbad504` | CMS Medicare Short-Stay Hospital Discharge Rankings, 2019 distribution | Low relevance context | Public DATA; CMS; temporal 2017–2025; ALT(21) | No description or structured geography; Lyme signal unverified |
| `candidate:18f7b3a8832924fd924899d76123150a` | Same CMS dataset, 2025 distribution | Low relevance alternate | Public DATA; CMS; temporal 2017–2025; ALT(21) | Revision versus alternate benefit not evidenced in link taxonomy |
| `candidate:1d0655ce17c73f2740b07557f68b7671` | Same CMS dataset, 2018 distribution | Low relevance alternate | Public DATA; CMS; temporal 2017–2025; ALT(21) | No description or county/Lyme variable evidence |
| `candidate:8d7097301652deb7b3b812a4fd016641` | NY ACT Admission to Discharge Outcomes, JSON | Irrelevant | Public DATA; description says behavioral-health outcomes by NY region; ALT(3) | Rights field absent; no Lyme connection |
| `candidate:c5933b503b91c9639666997f85fb9f46` | Same NY ACT dataset, XML | Irrelevant alternate | Same description, public DATA; ALT(3) | Rights field absent; no separate benefit |
| `candidate:012f83a0bfffb8d613654d8fa8bc349c` | CA Hospital Inpatient by Facility, 2024 pivot | Weak context | Public XLSX; CC-BY metadata; ALT(13) | No description, time field or Lyme/county fit |
| `candidate:04ef7a368a42be2b0eb4dcef090861cb` | Same CA facility dataset, 2018 pivot | Weak alternate | Public XLSX; ALT(13) | No version semantics beyond title; Lyme/county fit unknown |
| `candidate:10b792cc37f89be1438e033817675db5` | Same CA facility dataset, 2012 pivot | Weak alternate | Public XLSX; ALT(13) | No version semantics beyond title; Lyme/county fit unknown |
| `candidate:094037d7488dd8db6ea243c56f0f463f` | SAMHSA TEDS Admissions 2004 | Irrelevant | Public DATA; old treatment-episode title; ALT(1) | Description and Lyme connection absent |
| `candidate:0a2d70a66a1e87a70ac972d502c956b5` | SAMHSA TEDS Discharges 2007 landing page | Irrelevant alternate | Public landing page; ALT(1) | Description and Lyme connection absent |
| `candidate:152e898009f8364813633781d1966e39` | Infective endocarditis ICU article | Irrelevant | NIH landing page; ALT(1) | Dataset payload, coverage and Lyme connection absent |
| `candidate:46483fc37c00f8c25cf07b3811c8d3c1` | Organophosphate poisoning ICU article | Irrelevant | NIH DATA record; ALT(1) | Dataset status and Lyme connection absent |
| `candidate:00352914b8e107bcab4d66617e02d5d0` | VA Home Based Primary Care | Ambiguous / likely blocked | Controlled-access, non-public; VA; historical 1983–2014; no identity link | Description, geography, rights and Lyme variables unknown; license metadata does not grant access |
| `candidate:0f652f6405264880e03d192af7ab4ddf` | VA Patient Treatment File | Ambiguous / likely blocked | Controlled-access, non-public; diagnosis keywords; historical 1975–2014; no identity link | Description, geography, rights and Lyme variables unknown; license metadata does not grant access |
| `candidate:9d61827188ed9dd6898971f39dc38f94` | NY mental disorder and violent crime study | Irrelevant | API record; 1968–1988 study title; no identity link | Description, geography and Lyme connection absent |

## Aggregate and interpretation

- **25 real candidate resources human screened; 0 processed by the current semantic agent.** Recommendations: **not measured**, not zero-result model performance. Classification counts (`RELEVANT`, `POSSIBLY_RELEVANT`, `IRRELEVANT`, `INSUFFICIENT_EVIDENCE`, `BLOCKED`): **not measured**. Eligibility, deterministic score, priority, rationale, stop/abstention reason, and human directional correctness of agent outputs: **not measured**.
- **22/25** have observed alternate-distribution links; **0/25** were proved suppressed by application behavior. The remaining 3 have no identity-link rows. `already_governed=false` for all 25.
- **No agent top recommendations.** The CA county MDC file is the only clear human *investigate first* candidate in this particular sample, conditional on its diagnosis and county content. Other CA county resources may complement it. No clearly Lyme-specific high-value candidate is present in the completed candidate batch.
- In the 107-row source batch, 31 distinct titles/parent datasets appear; 104 rows have alternate-distribution links, 14 have descriptions, and 0 have populated structured `spatial`. These source observations suggest candidate selection and metadata completeness problems; no measured attribution can yet be made to semantic prompt, eligibility, relationship code, or ranking.
- An actual application defect has **not** been demonstrated by this audit. Explicitly unknown evidence, non-public VA access, and alternate-distribution handling are conservative controls. The current inability to measure product value is an **execution prerequisite blocker** plus a weak candidate mix, not evidence of model failure at this SHA.
- **Smallest next iteration:** supply the existing dedicated model authentication and owner-reviewed cost evidence, then run the unchanged supported DEV graph at this exact SHA against a pinned governed batch that includes several actually Lyme-relevant sources. Record candidate-level semantic outputs and human labels before selecting any code change. Do not tune from this human-only audit.

## Verification

`uv sync --extra dev --locked` succeeded. Offline v2 domain evaluation passed (11 domain and 16 receipt cases); v2 graph trajectory evaluation passed (21 cases). These are deterministic fixtures, not product-value evidence. Repository gates and final status are recorded in the issue comment.
