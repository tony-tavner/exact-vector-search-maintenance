# Data

## Source (plain files in `raw/onet_29_3/` after unpacking `data`)

O*NET 29.3 database (May 2025), Occupation Data and Skills tables, © U.S. Department of Labor, Employment and Training Administration (USDOL/ETA), CC BY 4.0. `onet_occupations.tsv` and `onet_skills.tsv` are the release files `Occupation Data.txt` and `Skills.txt`, renamed with unchanged content; `ATTRIBUTION.txt` gives the source URLs, SHA-256 sums and the required attribution.

The occupation table contains 1,016 O*NET-SOC codes; the skills table contains 61,530 ratings on the importance and level scales.

## Processed corpus (`processed/onet29_3_v1/`, archive `data`)

* `documents.jsonl`, `fragments.jsonl` — one document per occupation; one fragment joining title and description and, where skill data exist, one fragment joining title and skill names in source-identifier order (1,895 fragments; 137 occupations have descriptions only).
* `queries.jsonl` — one templated English query per occupation.
* `controlled_workloads.jsonl` — constructed applicability metadata and update events. These fields and events were constructed for the study and are not official requirements or admission rules.
* `splits.json` (also `../splits.json`) — assignment of whole SOC major groups to development (14 groups), validation (4) and final (5) splits. Only the development split was used in the paper.
* `skill_ratings.jsonl` — the ratings, kept for reference; no rating threshold was used to build fragments.
* `embedding_config.json` — encoder, preprocessing and scoring configuration.
* `embeddings_development/` — encoder input, raw JSON output, invocation record and the binary64 L2-renormalized vectors (`vectors.npy`) for the development split.

## Derived histories (`derived/EX01_2026-11-18_01/`, archive `data`)

Grouping and history-length scenarios of Section 5.4: four development families (SOC 55, 23, 51, 27), one occupation or groups of four occupations per document, 100 or 1,000 atomic batches.

## Model (`raw/models/nomic_embed_text/`)

Metadata, licence and manifest of the Nomic Embed Text 137M F16 weights. The weights themselves are not included; see the main README.
