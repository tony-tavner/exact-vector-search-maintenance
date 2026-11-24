# Exact vector search maintenance: invariance certificates and score caching

Artifact for the PVLDB Volume 20 (VLDB 2027) submission
**"End-to-End Cost of Exact Vector Search Maintenance for Personnel Security: Invariance Certificates and Score Caching"**
by Dmitry G. Rodionov, Evgenii A. Konnikov and Prokhor A. Polyakov (Peter the Great St. Petersburg Polytechnic University).

The repository contains the implementations compared in the paper (C1, C1-I01, B0–B6 and the C1 variants FLAT, SEPARATE, MARGIN and NO_CERT), the exhaustive snapshot oracle, the data preparation and workload generators, the experiment drivers, the analysis scripts, the O*NET 29.3 corpus and derived inputs, and the complete per-run records behind every reported measurement. A read-only script recomputes the headline numbers of the paper from the bundled records using only the Python 3 standard library.

## Quick start: verify the reported numbers

```sh
python3 reproduction/unpack_archives.py          # checks SHA-256 of every part, joins and extracts the archives
python3 reproduction/reproduce_results.py > recomputed.json
```

`unpack_archives.py` restores `data/`, `results/` and `reports/` in place (about 4.0 GB uncompressed) and verifies every extracted file against `archives/*.members.json`. `reproduce_results.py` then

* re-reads the 640 measured cold-start records of the short series, checks the SHA-256 of each `worker.json`/`validation.json` against the run index (directly, or through `archives/redactions.json` for records whose local paths were replaced, see below), and recomputes the seven C1/control total-time ratios of Table 3 and Figure 1;
* recomputes the C1-I01 contrasts of Table 4 and Figure 2b from the long-history records;
* recomputes the 6.71% conditional saving of Section 6.2 (Figure 2a) from the 42 B3 runs of the 14 occupational families.

Bootstrap intervals are copied from the preserved analysis records (`reports/e_stages/E05/.../precision_final.json`, `results/iterations/E07_2026-11-18_01/I01_analysis.json`); `scripts/e05_statistics.py` and `scripts/analyze_e07.py` contain the resampling code that produced them. No experiment, inference or network access is performed by these two commands.

## Where each result of the paper comes from

| Paper | Experiment id | Records (after unpacking) | Producing scripts |
|---|---|---|---|
| §4.1 data, splits | E01 | `data/processed/onet29_3_v1/`, `data/splits.json` | `scripts/prepare_data.py`, `scripts/build_e01_fixtures.py`, `tests/verify_e01_*.py` |
| §3.1–3.2 certificate bound, §6.3 numeric scope | E03 | `reports/e_stages/E03/E03_2026-11-18_03/`, `docs/numeric_certificate_C1.md`, `docs/proof_obligations.md` | `scripts/check_c1_fsum_certificate.py`, `scripts/capture_c1_numeric_runtime.py`, `scripts/c1_fp_environment_probe.c`, `scripts/build_e03_cases.py` |
| §3.3–3.4 implementations, Table 1 | E04 | `src/pvldb_a/`, `reports/e_stages/E04/` | `scripts/build_e04_native.py`, `tests/e04/check_implementation.py` |
| §5.1 Table 3, Figure 1; §5.3 Table 5 (P05 with the FLAT, SEPARATE, MARGIN and NO_CERT variants), P06 and P07; §6.1 Table 7 | E05 | `results/pilot_runs.jsonl`, `results/pilot/E05_2026-11-18_01/`, `reports/e_stages/E05/` | `scripts/prepare_e05_pilot.py`, `scripts/execute_e05_pilot.py`, `scripts/run_pilot.py`, `scripts/analyze_e05_pilot.py`, `scripts/e05_statistics.py` |
| §4.2 diagnostic profiles and geometry probes; §5.3 block-bound failures | E06 | `results/comparison/E06_2026-11-18_01/`, `reports/e_stages/E06/` | `scripts/profile_e06.py`, `scripts/audit_e06_geometry.py`, `scripts/report_e06.py` |
| §5.2 Table 4, Figure 2b; §6.2 Figure 2a; Table 8 latencies | E07 | `results/iterations/E07_2026-11-18_01/`, `reports/e_stages/E07/`, `reports/e_stages/E02/E02_2026-11-18_04/budget_reassessment.json` | `scripts/prepare_e07.py`, `scripts/execute_e07.py`, `scripts/run_e07_case.py`, `scripts/analyze_e07.py`, `scripts/supplement_e07.py`, `scripts/build_e07_i01.py`, `scripts/analyze_r02_e07_budget.py` |
| §5.4 Table 6 (grouping and history length) | EX01 | `data/derived/EX01_2026-11-18_01/`, `results/exploration/EX01_2026-11-18_01/`, `reports/exploration/EX01_2026-11-18_01/` | `scripts/prepare_ex01_redesign.py`, `scripts/execute_ex01_redesign.py`, `scripts/run_ex01_case.py`, `scripts/analyze_ex01_redesign.py` |
| §6.3 additional implementation checks (differential snapshots, batch kernel against canonical scores) | R02 | `reports/e_stages/R02/R02_2026-11-18_02/`, `reports/e_stages/R02/R02_2026-11-18_05/` | records only |

Each run directory contains `worker.json` (timers, spans, operation counters and published answers), `validation.json` (oracle comparison), `supervisor.json` (limits, timeouts and resource measurements) and, for cold-start runs, the encoder invocations under `embedding/`. Run directories are named `<experiment>_<phase>_b<block>_<history>_<method>`.

## Re-running the experiments

The measurements were taken on an Apple M4 Pro (24 GiB) under macOS 26.2 arm64 with CPython 3.9.6 and NumPy 2.0.2, one search thread and four encoder threads. `environment/manifest.json` and `environment/offline_setup.txt` record the exact interpreter, library and native-module hashes; `environment/native/` holds the build receipts and the compiled native kernel (`src/pvldb_a/native.c`).

The numerical certificate is proved for this specific environment (round-to-nearest binary64 products summed by the pinned `math.fsum` of CPython 3.9.6 on arm64, FPCR = 0). On a different interpreter, platform or rounding mode, the bound and the scorer have to be revalidated with `scripts/check_c1_fsum_certificate.py` and `scripts/capture_c1_numeric_runtime.py` before timing results can be compared.

Cold-start runs require the text encoder:

* model: Nomic Embed Text 137M, F16 GGUF weights with SHA-256 `970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6` (Apache 2.0, see `data/raw/models/nomic_embed_text/LICENSE.txt`). The weights are not redistributed here; they are the layer listed in the included Ollama manifest (`data/raw/models/nomic_embed_text/ollama_manifest.json`) of the `nomic-embed-text` model. Place the file at `data/raw/models/nomic_embed_text/weights.gguf` and check its SHA-256;
* runtime: llama.cpp 0.5.0, build 11146, commit `7fe450e19`, mean pooling, 2,048-token context, prefixes `search_document: ` / `search_query: ` (`data/processed/onet29_3_v1/embedding_config.json`).

Runs with precomputed vectors use `data/processed/onet29_3_v1/embeddings_development/vectors.npy` and do not need the encoder. The drivers write new run directories and refuse to overwrite existing ones; use a fresh working copy and a new run identifier for any new measurement. Several drivers and analysis scripts print their reports in Russian; field names in all JSON records are in English.

## Data and licences

* O*NET 29.3 (May 2025), Occupation Data and Skills tables, © U.S. Department of Labor, Employment and Training Administration (USDOL/ETA), licensed under CC BY 4.0. The original files with their SHA-256 sums are in `data/raw/onet_29_3/`; see `ATTRIBUTION.txt`. Queries, applicability fields and update histories were constructed for this study; they are not official requirements and are not endorsed by USDOL/ETA.
* The B4 and B5 controls are our exact adaptations of the published Simpfer and Simpfer++ algorithms; the MIT licences of the authors' reference implementations are reproduced in `environment/licenses/`.
* Code in this repository: MIT licence (`LICENSE`).

## Funding

This study was financed as part of the project "Science-based Approach to Ensuring Personnel Security of the Region as a Dynamic System: Theory, Methodology, Tools" (FSEG-2026-0010).

## Repository layout

```
src/            implementations (pvldb_a: original C1 and controls, A-E04-0.1; pvldb_a_e07_i01: C1-I01)
scripts/        data preparation, experiment drivers, analysis and plotting
tests/          implementation checks and contract fixtures
configs/, protocol/, environment/   implementation registry, frozen measurement protocols, environment records
docs/           technical notes (in Russian): answer contract, certificate bound and proof obligations, baseline adaptations
data/           O*NET source files and model metadata (plain); processed and derived inputs (archived)
archives/       compressed parts of data/, results/ and reports/, per-file SHA-256 lists, path-redaction map
reproduction/   unpack_archives.py, reproduce_results.py
```

Per-run snapshots of the workstation process table taken for background-load monitoring are not included, because they list unrelated software running on the authors' workstation.

Absolute paths of the measurement machine inside the records were replaced after the measurements by `<workdir>` (the root of the research working copy) and `<home>` (the home directory of the measurement account); no other byte was changed. `archives/redactions.json` lists every affected file with the SHA-256 recorded at measurement time, which the run indexes and other records refer to, and the SHA-256 of the published file. The correspondence between the two hashes can be confirmed only against the original records, which the authors retain.
