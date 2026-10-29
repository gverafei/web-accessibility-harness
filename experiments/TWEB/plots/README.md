# Paper plots

All numerical figures from the article are collected here and named by their
paper number. Snapshot miniatures are kept separately in each experiment’s
`thumbnails/` folder. Figures 1–3 are conceptual diagrams rather than data plots.

| Paper figure | Contents | Experiment | Python generator |
| --- | --- | --- | --- |
| [Figure 4](figure-04-repeatability-alignment.png) | Harness determinism across repeated runs | [1](../experiment-1/README.md) | [plot_results.py](../experiment-1/plot_results.py) |
| [Figure 5](figure-05-cut-fidelity-resources.png) | Retention and resource distributions for P0–P4 | [2](../experiment-2/README.md) | [plot_results.py](../experiment-2/plot_results.py) |
| [Figure 6](figure-06-cut-taxonomy-failures.png) | Taxonomic failures by domain | [2](../experiment-2/README.md) | [plot_results.py](../experiment-2/plot_results.py) |
| [Figure 7](figure-07-strategy-retention-cost.png) | Fixed-policy cost and content retention | [2](../experiment-2/README.md) | [plot_results.py](../experiment-2/plot_results.py) |
| [Figure 8](figure-08-model-resource-shares.png) | Resource shares by model configuration | [2](../experiment-2/README.md) | [plot_results.py](../experiment-2/plot_results.py) |
| [Figure 9](figure-09-time-worker-family-tradeoff.png) | Model family and reasoning effort | [3](../experiment-3/README.md) | [plot_results.py](../experiment-3/plot_results.py) |
| [Figure 10](figure-10-p5-cost-quality.png) | P5 quality and preservation comparison | [4](../experiment-4/README.md) | [plot_results.py](../experiment-4/plot_results.py) |
| [Figure 11](figure-11-p5-resource-bars.png) | P5 resource comparison | [4](../experiment-4/README.md) | [plot_results.py](../experiment-4/plot_results.py) |
| [Figure 12](figure-12-model-strategy-iteration-returns.png) | Additional correction across evaluated iterations | [2](../experiment-2/README.md) | [plot_results.py](../experiment-2/plot_results.py) |
| [Figure 13](figure-13-model-strategy-cost.png) | P5 versus fixed policies under joint criteria | [4](../experiment-4/README.md) | [plot_results.py](../experiment-4/plot_results.py) |
| [Figure 14](figure-14-model-strategy-preservation.png) | Correction and content preservation frontier | [4](../experiment-4/README.md) | [plot_results.py](../experiment-4/plot_results.py) |

The generators use the shared [`plotting/`](../plotting/) library.

## Regenerate

From the repository root:

```bash
python3 -m pip install -r experiments/TWEB/requirements.txt
python3 experiments/TWEB/plot_all.py
python3 experiments/TWEB/verify.py
```

The generators read the CSV evidence in their respective experiment folders.
No database, application services, live pages or model calls are used. Select a
subset with `--experiment 1 2`, or build elsewhere with `--output-dir PATH`.

`metadata/experiment-N.json` records the figure numbers, source and script hashes,
plotted summaries, image resolution and output hashes. `metadata/p5-comparison.json`
contains the detailed adaptive-policy comparison. Each PNG has at least 1000 dpi
at the article’s maximum seven-inch width.
