# Experiment 4 supplementary evidence

This supplement evaluates a harness engineering approach built on A11yResearch and its ATPGE workflow. The harness governs source admission, intervention permissions, feedback, resource limits, and result selection.

This self-contained folder documents thirty selected P5 executions on thirty
frozen sources, their 128 evaluated page versions, and the comparison with
450 source-matched fixed P0–P4 conditions. It contains a reader report, exported
experiment evidence and sixty small saved-capture thumbnails. Full page payloads are not included in this reader package.

## Regenerate the PDF

Install Python 3.10 or later with `pypdf`, and a LaTeX distribution with `latexmk` and the ACM
fonts. The manuscript's exact `acmart.cls` is included with its license. Run:

```sh
python3 generate.py
```

This compiles editable `main.tex` into `supplementary.pdf`, preserving manual TeX
edits. To explicitly rebuild the source from the exported evidence:

```sh
python3 generate.py --refresh-source
```

Generation needs no SQLite installation, running services, Azure, live website or
model API. Compilation uses an automatically removed temporary build directory.
The source refresh verifies the evidence and thumbnail SHA-256 checksums first.

## Paper figures

The paper’s graphs are collected in [../plots/](../plots/README.md), alongside
the experiment folders. This experiment contributes:

| Paper figure | Contents |
| --- | --- |
| [Figure 10](../plots/figure-10-p5-cost-quality.png) | P5 quality and preservation comparison |
| [Figure 11](../plots/figure-11-p5-resource-bars.png) | P5 resource comparison |
| [Figure 13](../plots/figure-13-model-strategy-cost.png) | P5 versus fixed policies under joint criteria |
| [Figure 14](../plots/figure-14-model-strategy-preservation.png) | Correction and content preservation frontier |

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

`../plots/metadata/experiment-4.json` binds input data, plotting code, numerical
summaries and generated images. Use `--output-dir PATH` to reproduce the figures
elsewhere. Plotting does not edit or compile `main.tex`.

## Files and units

| File | Contents |
| --- | --- |
| `data/sources.csv` | Thirty source identities, input hashes, baseline audits and saved-capture bindings |
| `data/runs.csv` | Thirty selected outputs, executed/planned routes, repair and planner identities, retention, taxonomy coverage, visual decisions/rationales and execution resources |
| `data/iterations.csv` | Evaluated versions for traceability, with sequential candidate indices, generation slots, selected/retained markers and action/decision/retrieval identities |
| `data/fixed-conditions.csv` | The 450 P0–P4 endpoints, three configurations per policy and source, used in the source-matched comparison |
| `data/requests.csv` | Completed model invocations; model/runtime identities, request/response hashes, tokens, durations and charges |
| `data/prompts.csv` | Planning, generation, component-planning, diagnosis and continuation requests, linked to run, iteration, instructions and request hashes |
| `data/message-parts.csv` | Role, type, size and hash of each exported request part; full page/image payloads are excluded from this reader package |
| `data/prompt-instructions.json` | Deduplicated saved instruction/feedback excerpts; complete supplied page context is bound by its request hash |
| `data/prompt-examples.json` | Recorded planner, constrained-repair and ACT RAG examples used in the report |
| `data/decisions.json` | All 240 recorded closed choices, available alternatives, observed state, route plans and reasons; these include coordinator stopping choices and are not all paid model calls |
| `data/rag.json` | ACT corpus/query hashes, requested rules and injected example identities for each measured version |
| `data/skills.json` | Four saved injected skill versions and instructions |
| `data/accounting.csv` | Published execution resources linked to the included receipt charges for every run |
| `data/task-accounting.csv` | Complete workflow call counts, input/output tokens and charges grouped by task role |
| `data/protocol.json` | Cohort, saved comparison hash, per-run controller/model/runtime settings and export integrity checks |
| `data/checksums.json` | SHA-256 checks for the exported evidence and sixty thumbnails |
| `thumbnails/` | Thirty original and thirty selected-output JPEG thumbnails, at most 480 pixels in the largest dimension |
| `main.tex`, `generate.py` | Editable report and standalone source generator/compiler |

Axe counts issue instances; Lighthouse uses its 0–100 accessibility score.
Retention columns are percentages; composite retention averages text, link
destinations and image references. Taxonomy coverage is a 0–1 proportion of
conclusive applicable assessments. Time is in seconds, tokens are counts, and
charges are USD. Run costs include complete planning, generation and assessment.
Call elapsed time and complete operational execution time are distinct.
The report averages three fixed configurations within each source before
comparing them with the selected P5 execution; every source has equal weight.

Analyses use one selected output per source. Intermediate evaluated pages remain
traceability records. `candidate_index` numbers measured pages consecutively;
`iteration` identifies their recorded generation slot. Routes list actions that
produced evaluated pages. Complete costs and tokens reconcile across `runs.csv`,
`accounting.csv` and `task-accounting.csv`.

`chosen` means selected by the experimental criteria, not visually accepted.
Original `admitted`/`rejected` visual judgments and their full rationales remain in
`runs.csv`. Separate usability checks admit 26 selected outputs and flag four;
`functional_status` and `functional_reasons` retain those results independently
of visual admission. Unassessed checks do not count as passes. The report crops thumbnails
from saved captures; rebuilding does not acquire a page or alter a review.

P5 selects actions from the current page profile, measured findings, intervention
permissions and within-run feedback, without cross-run history or memory. All
thirty executions use GPT-Luna 6 Decisions. Plans, executed actions, measured
versions and stopping choices remain separate. The comparison covers thirty
source-matched pages; it does not constitute an unseen-domain transfer test.

The thirty-run cost is USD 4.10520759. Artifact references use stable SHA-256
identifiers; measured content hashes and provider call identities remain recorded
for traceability. The reported execution resources include the complete workflow.
