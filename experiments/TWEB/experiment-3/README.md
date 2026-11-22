# Experiment 3 supplementary evidence

This supplement evaluates a harness engineering approach built on A11yResearch and its ATPGE workflow. The harness governs source admission, intervention permissions, feedback, resource limits, and result selection.

This self-contained folder documents the twelve published P4 model/effort
configurations on one frozen TIME source and their twenty evaluated page versions.
It contains experiment evidence and small saved-capture thumbnails. Full page payloads are not included in this reader package.

## Paper figures

The paper’s graphs are collected in [../plots/](../plots/README.md), alongside
the experiment folders. This experiment contributes:

| Paper figure | Contents |
| --- | --- |
| [Figure 9](../plots/figure-09-time-worker-family-tradeoff.png) | Model family and reasoning effort |

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

`../plots/metadata/experiment-3.json` binds input data, plotting code, numerical
summaries and generated images. Use `--output-dir PATH` to reproduce the figures
elsewhere. Plotting does not edit or compile `main.tex`.

## Regenerate the PDF

Install Python 3 with `pypdf`, and a LaTeX distribution with `latexmk` and the ACM
fonts. The exact `acmart.cls` used by the manuscript is included with its license.
Run from this folder:

```sh
python3 generate.py
```

This compiles the editable `main.tex` into `supplementary.pdf`, preserving manual
TeX edits. To explicitly rebuild that source from the exported evidence:

```sh
python3 generate.py --refresh-source
```

Generation needs no SQLite, running services, Azure, live website, or model API.
Compilation uses an automatically removed temporary build directory.

## Files and units

| File | Contents |
| --- | --- |
| `data/sources.csv` | Frozen source identity, input hash, baseline audits and original snapshot binding |
| `data/runs.csv` | Twelve selected results, repair configurations, retention, taxonomy coverage, visual decisions/rationales, resources and artifact identities |
| `data/iterations.csv` | All twenty evaluated versions, audit paths, selected/retained markers, decision and retrieval identities |
| `data/requests.csv` | All 271 recorded calls belonging to the selected executions, with request/response identifiers, models, tokens, duration and charge |
| `data/generation-prompts.csv` | Twenty generation/refinement calls linked to run, iteration, instructions and complete request hashes |
| `data/message-parts.csv` | Role, type, size and hash of every generation-request part; original page/image payloads are excluded from this reader package |
| `data/prompt-instructions.json` | Deduplicated recorded instruction/feedback excerpts; complete Markdown and acquired-page context are represented by their hashes |
| `data/prompt-examples.json` | Initial generation and local-refinement examples used in the reader report |
| `data/rag.json` | ACT corpus/query hashes, requested rules and injected example identities for every measured iteration |
| `data/skills.json` | Three injected skill versions and their instructions |
| `data/taxonomy.csv` | Selected-output failures, opportunities, conclusive coverage and unassessed checks by category |
| `data/protocol.json` | Frozen input, common initial-message hash, per-run model/provider settings, limits and export provenance |
| `data/checksums.json` | SHA-256 checks for the exported evidence and thirteen thumbnails |
| `thumbnails/` | One original and twelve selected-output thumbnails, each at most 480 pixels in its largest dimension |
| `main.tex`, `generate.py` | Editable report and standalone source generator/compiler |

Axe counts issue instances. Lighthouse uses its 0–100 accessibility score.
Retention columns are percentages; composite retention averages text, links and
images. Taxonomy coverage is a 0–1 proportion of conclusive applicable assessments.
Time is in seconds, tokens are counts and charges are USD. Per-run cost includes
all its recorded calls. Wall-clock durations remain saved execution values.

`chosen` means selected by the experimental audit criteria, not visually accepted.
The original `admitted`/`rejected` visual decisions and their complete rationales
remain in `runs.csv`. No review or snapshot is regenerated during a build.
Request hashes bind complete requests; instruction hashes bind exported excerpts.
Unassessed checks do not count as passes.
