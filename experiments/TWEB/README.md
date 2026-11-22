# TWEB experimental evidence

Companion evidence for **Harness Engineering for Web Accessibility:
Orchestrating Automated Remediation with Agents and LLMs**, by Guillermo
Vera-Amaro and José Rafael Rojano-Cáceres.

| Experiment | Question | Sources | Runs | Evaluated versions |
| --- | --- | ---: | ---: | ---: |
| [1](experiment-1/README.md) | Repeatability under fixed P1/P2 controls | 5 | 30 | 116 |
| [2](experiment-2/README.md) | Fixed intervention trade-offs, P0–P4 | 30 | 450 | 1,074 |
| [3](experiment-3/README.md) | Model family and reasoning effort under P4 | 1 | 12 | 20 |
| [4](experiment-4/README.md) | Page-guided P5 selection without history | 30 | 30 | 128 |

The four comparisons contain 522 selected runs and 1,338 evaluated page versions
on 35 distinct frozen sources. Sources overlap between experiments. Intermediate
versions support traceability; they are not additional independent page samples.

## Reading a package

Each experiment folder contains:

- `data/sources.csv`: source identities, URLs and baseline measurements.
- `data/runs.csv`: one row per selected run with model/strategy, outcome,
  preservation and resource measurements.
- `data/iterations.csv`: measured candidate history, with the selected version
  marked separately from retention during the loop.
- `data/requests.csv`: recorded model calls, usage and charges. Accounting and
  inclusion columns distinguish the scope used for the reported totals.
- Prompt instruction, example and message-part records: recorded instructions
  and SHA-256 references link iterations to the evidence supplied to models;
  complete captured website payloads are not part of this reader export.
- `data/skills.json` and `data/protocol.json`: injected task instructions,
  controller/model configuration and experimental scope.
- `data/checksums.json`: file-level integrity checks for the evidence and images.
- `thumbnails/`: compact reference and selected-output thumbnails.
- `plot_results.py`: the experiment’s figure-generation entry point.
  All four scripts use the shared [`plotting/`](plotting/) library; generated
  graphs are collected in [`plots/`](plots/README.md).
- `main.tex`, `generate.py`, `acmart.cls`, `LICENSE.acmart` and
  `supplementary.pdf`: editable reader report, generator and the ACM class.

Additional files document ACT retrieval, decisions, taxonomy, paired statistics
or cost allocation where applicable. Each experiment's README defines its exact
file set and metric units. A selected output is the retained experimental result;
selection does not itself imply visual acceptance or WCAG conformance.

## Verify offline

From the repository root:

```bash
python3 experiments/TWEB/verify.py
```

The verifier uses only Python's standard library. It checks paths and SHA-256
bindings, run membership, version counts and the chosen candidate per run.
It also checks the generated figures against their input, script and image hashes,
reporting stale bindings if any of these change. It never connects to a database,
acquires a page or requests a model response.

## Paper plots

[`plots/`](plots/README.md) sits alongside `experiment-1/` through `experiment-4/`
and contains all eleven numerical figures from the article. Filenames include
the paper number, from `figure-04-repeatability-alignment.png` to
`figure-14-model-strategy-preservation.png`. The index links each figure to its
experiment and Python source. Figures 1–3 are conceptual architecture diagrams.

Each experiment keeps its snapshot miniatures in `thumbnails/`. These are
separate from the numerical graphs in the shared `plots/` directory.

```bash
python3 -m pip install -r experiments/TWEB/requirements.txt
python3 experiments/TWEB/plot_all.py
python3 experiments/TWEB/verify.py
```

The generators use the same local CSV evidence as the reader reports. No private
analysis files, database, provider credentials, live websites or model calls are
required. Input data, code, plotted summaries and output hashes are recorded in
`plots/metadata/experiment-N.json`.

To select experiments or write a separate reproduction directory:

```bash
python3 experiments/TWEB/plot_all.py --experiment 2 3 --output-dir /tmp/tweb-plots
```

Each experiment can also be plotted using its own `plot_results.py`.
Drawing functions, the model palette and evidence checks live once in `plotting/`.
Both commands write numbered figures to the shared directory by default. Scientific measurements,
manuscript text and supplementary PDFs are not changed by plotting.

## Rebuild a reader report

Install Python 3.10 or later, the dependencies below and a LaTeX distribution with `latexmk`
and ACM fonts. The included class is used from the experiment folder.

```bash
python3 -m pip install -r experiments/TWEB/requirements.txt
python3 experiments/TWEB/experiment-1/generate.py
```

Use the analogous script for experiments 2–4. By default, compilation preserves
edits to `main.tex`. Add `--refresh-source` only to regenerate the source from the
exported CSV/JSON evidence. Build intermediates are temporary and no application
services are required.
