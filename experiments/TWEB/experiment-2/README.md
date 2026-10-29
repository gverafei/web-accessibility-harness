# Experiment 2 supplementary evidence

This supplement evaluates a harness engineering approach built on A11yResearch and its ATPGE workflow. The harness governs source admission, intervention permissions, feedback, resource limits, and result selection.

This self-contained folder documents thirty frozen domains under five policies
(P0–P4) and three repair configurations: 450 selected runs and 1,074 evaluated
page versions. It includes the ACM reader report, quantitative evidence and 480
small thumbnails: thirty original pages and all 450 selected outputs.

## Paper figures

The paper’s graphs are collected in [../plots/](../plots/README.md), alongside
the experiment folders. This experiment contributes:

| Paper figure | Contents |
| --- | --- |
| [Figure 5](../plots/figure-05-cut-fidelity-resources.png) | Retention and resource distributions for P0–P4 |
| [Figure 6](../plots/figure-06-cut-taxonomy-failures.png) | Taxonomic failures by domain |
| [Figure 7](../plots/figure-07-strategy-retention-cost.png) | Fixed-policy cost and content retention |
| [Figure 8](../plots/figure-08-model-resource-shares.png) | Resource shares by model configuration |
| [Figure 12](../plots/figure-12-model-strategy-iteration-returns.png) | Additional correction across evaluated iterations |

From this folder, regenerate them with:

```sh
python3 plot_results.py
```

Install dependencies with `python3 -m pip install -r ../requirements.txt`.
The script reads this experiment’s CSV files, validates their checksums and
writes the numbered PNGs to `../plots/`. Drawing routines, styles and evidence
checks are shared in [`../plotting/`](../plotting/). It does not connect to a database,
application service, live page or model API. Snapshot miniatures used by the
reader report are in `thumbnails/`.

`../plots/metadata/experiment-2.json` binds input data, plotting code, numerical
summaries and generated images. Use `--output-dir PATH` to reproduce the figures
elsewhere. Plotting does not edit or compile `main.tex`.

## Regenerate the PDF

Install Python 3 with `pypdf`, and a LaTeX distribution containing `latexmk` and
the ACM fonts. The manuscript's exact `acmart.cls` is included with its license.
Run from this folder:

```sh
python3 generate.py
```

This compiles editable `main.tex` into `supplementary.pdf`, preserving manual
edits. To explicitly rebuild the source from the exported evidence:

```sh
python3 generate.py --refresh-source
```

Generation requires no SQLite installation, running services, live website,
Azure connection or model API. Source refresh checks the exported SHA-256
manifest. Compilation uses an automatically removed temporary build directory.

## Files and units

| File | Contents |
| --- | --- |
| `data/sources.csv` | Thirty source identities, input hashes, baseline audits, source URLs and original-capture bindings |
| `data/runs.csv` | All 450 selected results by domain, policy and repair configuration, with retention components, taxonomy coverage, visual judgments/rationales and execution resources |
| `data/iterations.csv` | All 1,074 measured versions, audit paths, source/parent references, selected/retained markers, durations and decision/retrieval references |
| `data/requests.csv` | All 11,881 recorded calls included in the analyzed executions, with model, call/request/response references, tokens, duration, status and USD charge |
| `data/prompts.csv` | The 3,136 generation, planning, diagnosis and continuation requests, linked to run, iteration where applicable, instruction hash and complete-request hash |
| `data/message-parts.csv` | Role, type, size and hash of each generation/planning request part |
| `data/prompt-instructions.json` | Deduplicated recorded instruction and feedback excerpts |
| `data/prompt-examples.json` | Recorded P0–P4 examples and an ACT RAG excerpt used in the reader report |
| `data/rag.json` | ACT corpus/query hashes, requested rules and injected case identities per measured version |
| `data/skills.json` | Six injected task-skill versions and their instructions |
| `data/decisions.json` | Recorded closed choices, available alternatives and reasons; these are distinct from paid model calls |
| `data/taxonomy.csv` | Original and selected failures, judged/applicable opportunities, unassessed checks and coverage by category |
| `data/taxonomy-types.json` | Saved original/selected outcomes by violation type and assessment references |
| `data/paired-statistics.json` | Saved domain-paired policy and effort contrasts, effects, bootstrap intervals, exact probabilities, Holm results and analysis settings |
| `data/accounting.csv` | Published run costs reconciled with the included receipt charges |
| `data/bindings.json` | Selected artifacts, measured attempts, condition hashes and included call identities |
| `data/protocol.json` | Cohort and source hashes, deduplicated model/controller/runtime configurations, task limits and export integrity checks |
| `data/checksums.json` | SHA-256 checks for the exported evidence and 480 thumbnails |
| `thumbnails/` | Saved original/selected JPEG thumbnails, each at most 320 pixels in its largest dimension |
| `main.tex`, `generate.py` | Editable report and standalone source generator/compiler |

Axe counts issue instances. Lighthouse is its 0–100 accessibility score. Retention
columns are percentages; composite retention averages text, original link
destinations and source image references. Taxonomy coverage is a 0–1 proportion
of conclusive applicable assessments. Unassessed checks do not count as passes.
Times are seconds, token values are counts and charges are USD. Report columns
label tokens in thousands where indicated. The published total is USD 45.693977785.
Run clocks and individual provider-call durations are distinct measurements.

Every domain has the same fifteen policy/configuration conditions. The report
preserves each final output and its measured outcomes.
`chosen` denotes experimental selection, independently of the saved automatic
visual judgment. P0's ninety outputs are measured under the same outcome
instruments; its generation request contains no supplied audit findings.

Artifact references use stable hashes of catalogue identifiers. Input, snapshot
and request SHA-256 fields bind actual payloads; provider call identities remain
recorded. Full HTML/image payloads are excluded from this reader package.
Rebuilding this report does not acquire pages, run models or alter human reviews.
