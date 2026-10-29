# Experiment 1 supplementary evidence

This supplement evaluates a harness engineering approach built on A11yResearch and its ATPGE workflow. The harness governs source admission, intervention permissions, feedback, resource limits, and result selection.

This folder contains the evidence needed to regenerate the Experiment 1
supplementary PDF. It is an experiment record, separate from the web-page dataset.
Generation uses only the files in this folder, without the prototype's database,
running services, live websites, or model calls.

## Paper figures

The paper’s graphs are collected in [../plots/](../plots/README.md), alongside
the experiment folders. This experiment contributes:

| Paper figure | Contents |
| --- | --- |
| [Figure 4](../plots/figure-04-repeatability-alignment.png) | Harness determinism across repeated runs |

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

`../plots/metadata/experiment-1.json` binds input data, plotting code, numerical
summaries and generated images. Use `--output-dir PATH` to reproduce the figures
elsewhere. Plotting does not edit or compile `main.tex`.

## Build the PDF

Requirements: Python 3 with `pypdf`, `latexmk`, and a LaTeX installation supporting
`acmart` and its fonts. The exact ACM class used by the paper is included here.

```sh
python3 generate.py
```

This compiles `main.tex` to `supplementary.pdf`. Edit `main.tex` directly and run the
same command to rebuild it; compilation preserves those edits.

To explicitly regenerate the TeX from the exported evidence instead:

```sh
python3 generate.py --refresh-source
```

## Exported evidence

| File | Contents |
| --- | --- |
| `data/sources.csv` | Five frozen source identities, baseline audits and thumbnail bindings |
| `data/runs.csv` | Thirty runs, selected results, taxonomy, coverage, retention, time, tokens and costs |
| `data/iterations.csv` | All 116 measured versions, proposal order, audit identifiers and selection markers |
| `data/requests.csv` | Recorded request identifiers, models, roles, hashes, tokens and charges, including shared source assessments |
| `data/generation-prompts.csv` | Each of the 166 generation calls linked to its run, iteration, original request hash and recorded instructions |
| `data/prompt-instructions.json` | Deduplicated verbatim instruction excerpts for those calls, including refinement instructions; page payloads are excluded from this reader package |
| `data/prompt-examples.json` | Verbatim recorded instruction excerpts and their request references |
| `data/skills.json` | Injected skill versions and instructions |
| `data/protocol.json` | Execution limits, accounting scope and export provenance |
| `data/checksums.json` | SHA-256 of the exported evidence and thumbnails |
| `thumbnails/` | Thirty-five viewport thumbnails, each at most 480 pixels wide |
| `main.tex`, `acmart.cls` | Editable report and the ACM class |
| `generate.py` | Standalone source generator and compiler |

The report uses the saved source and selected-output snapshot bindings. Each
thumbnail's original snapshot identifier and hash remain in the CSV records.
Only the small thumbnails are packaged. Shared source-assessment costs are divided
equally across each source's six selected runs; original request ownership remains
visible in the request ledger.

Counts are per run or evaluated page version as named in each file. Axe records
issue instances; Lighthouse uses its 0–100 accessibility score. Retention columns
are percentages, taxonomy coverage columns are proportions from 0 to 1, elapsed
time is in seconds, and charges are USD. `chosen` identifies the retained output;
it does not imply visual acceptance. Generation calls can outnumber measured
versions when a response is invalid, unchanged, or retried. A request hash binds
the complete original request; an instruction hash binds only the exported
instruction excerpt.

The initial package was exported from saved experiment evidence with
`../tools/export_experiment_1.py`. That optional adapter is separate from this
folder's standalone generator. The generator validates the exported files before
rebuilding the data-derived source.
