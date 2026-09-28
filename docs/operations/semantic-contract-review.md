# Candidate B semantic contract review (DEV)

This review used application main `3ff44616d29f302367b3e9d090d2c4182060f6b7`
and the pinned governed discovery snapshot
`7b027ee2-e881-4c5d-9bd3-a1c6477795bb`. It inspects only the retained
candidate observation view and the observable prompt/schema; it does not inspect
model reasoning or raw catalog payloads.

## Observable v1 classification contract

`OpenAIResponsesPlanner._invoke` combined `_SYSTEM` with
`_TASK_INSTRUCTIONS["classify candidate"]` under prompt version
`dataset-discovery-openai-semantic-v1`. `BoundedModelPlanner.classify` supplied
the candidate summary and allowlisted observations to `_ClassificationOutput`
(`CandidateAnalysis` and `RankingDimensions`). The system instruction treated
candidate metadata as untrusted, required provided observation IDs and exact
observed values, prohibited approval/ingestion/rights claims, and required null
dimensions for missing evidence. The task instruction required citations for
scored dimensions and inferences but did not define the investigation threshold,
the 0–2 relevance rubric, or when to select `INSUFFICIENT_EVIDENCE`. The enum also
allowed `RELEVANT`, `POSSIBLY_RELEVANT`, `IRRELEVANT`, and `BLOCKED`. The
deterministic validator requires each scored relevance citation to refer to a
retained `title`, `description`, `keywords`, or `resource_title` observation.

**Finding B — prompt/rubric ambiguity.** The code already permits cited
relevance alongside unknown optional dimensions, and deterministic ranking
penalizes rather than abstains on those unknowns. The prompt did not explicitly
separate investigation eligibility from fuller characterization. A model could
therefore treat missing optional fields as overall insufficiency. No instruction
explicitly required ingestion readiness, so this was ambiguity, not an explicit
stronger gate. The governed evidence was present, so finding D did not apply.

## Safe Candidate B input

The classification input consisted of the candidate summary and one retained
observation. The summary identified candidate
`candidate:afdb1f0d5c1cedfe97f99b0d5e7448f6`, catalog dataset
`4321e7f1e6c0251e7a12384e35751c604e788803911f4ce155ef14ed8ec1b5ef`,
catalog resource `9d545c79fff0a7c51cb7f4ce0c0910489581cc76ab0fdc3fdfbc7a0558f5dd6c`,
the title below, and publisher U.S. Geological Survey. Observation
`84564275a83cc8f5ebc716f3c175b834afde314adfa28ce9c7baae5448a8e9dd`
had metadata SHA-256 `4c671e6e562ad0d7abc9ab567b4f411adbbef1a3577eca383365e5860e7a3458`.
Only non-null allowlisted fields entered the model input:

| Field | Retained value |
| --- | --- |
| title | Blacklegged tick nymph densities, tickborne pathogen prevalence, and white-tailed deer densities in eight national parks in the eastern United States from 2014-2022 |
| publisher | U.S. Geological Survey |
| description | The data presented here are blacklegged tick nymph densities, white-tailed deer densities, and Borrelia burgdorferi (causative agent of Lyme disease) prevalences for eight national parks in the eastern United States from 2014-2022. |
| resource title / role / type | Digital Data / access / API |
| canonical URL | https://doi.org/10.5066/P9LSI8K9 |
| parent dataset ID | `4321e7f1e6c0251e7a12384e35751c604e788803911f4ce155ef14ed8ec1b5ef` |
| spatial | `-80.0000, 37.6000, -71.0000, 41.3000` |
| keywords | Catoctin Mountain Park; Chesapeake and Ohio Canal National Historical Park; District of Columbia; Fire Island National Seashore; Gettysburg National Military Park; Manassas National Battlefield Park; Maryland; Mid Atlantic; New York; Pennsylvania; Prince William Forest Park; Rock Creek Park; Virginia; biota; disease vectors; health; wildlife disease; wildlife population management; zoonotic diseases; catalog source tag |
| theme | geospatial |
| access level | public |
| modified | 2023-12-14T00:00:00Z |
| distribution description / format / media type | Landing page for access to the data / XML / application/http |
| catalog record / documentation | `http://datainventory.doi.gov/id/dataset/USGS_637cfb9bd34ed907bf73c08c` / `https://catalog.data.gov/harvest_record/713aaac6-4342-4990-9d7f-d0255efe32df` |

`issued`, `temporal`, and `license` were null in the retained view and omitted
from `field_values`. The description itself explicitly supports a cited Atlas
relevance judgment; its dates may support a cited time judgment, but no temporal
field may be invented. The classifier did not receive the graph's deterministic
`ALTERNATE_DISTRIBUTION` relationship as part of its `classify` input; ranking
received that relationship afterward. The previous model output recorded
`relevance_to_request` as unknown and all eight dimensions null.

## v2 correction

Prompt version `dataset-discovery-openai-semantic-v2` defines the question as
human investigation, gives a 0–2 relevance rubric, explicitly permits cited
description/title/keyword evidence, and leaves unsupported optional dimensions
null. It reserves `INSUFFICIENT_EVIDENCE` for missing minimal relevance or
required candidate eligibility, without claiming approval or rights clearance.
The old config remains available for audit. The new config changes only the
prompt version; model, reasoning, output cap, validator, ranking formula, and
Snowflake observation projection retain their prior contracts.
