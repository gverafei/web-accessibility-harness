"""Regenerate the model/effort figure from this experiment's selected outputs."""
import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from plotting.evidence import bind_inputs, read_csv, save_manifest
from plotting.model_families import plot

FIGURES = {
    'time-worker-family-tradeoff': (9, 'fig:worker-family-tradeoff'),
}


def load_rows():
    rows = read_csv(PACKAGE, 'runs.csv')
    sources = read_csv(PACKAGE, 'sources.csv')
    if len(sources) != 1 or len(rows) != 12:
        raise ValueError('Expected one frozen source and twelve configurations')
    for row in rows:
        if row['input_sha256'] != sources[0]['input_sha256']:
            raise ValueError('Unmatched frozen input: ' + row['profile'])
        for field in ('axe', 'lighthouse', 'cost_usd', 'content_retention',
                      'text_percent', 'links_percent', 'images_percent'):
            row[field] = float(row[field])
    if len({row['profile'] for row in rows}) != 12:
        raise ValueError('Duplicate repair configuration')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=PACKAGE.parent / 'plots')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = bind_inputs(PACKAGE, ('sources.csv', 'runs.csv'))
    rows = load_rows()
    statistics = plot(rows, output)
    statistics['selected_configurations'] = len(rows)
    save_manifest(PACKAGE, output, inputs, FIGURES, statistics)


if __name__ == '__main__':
    main()
