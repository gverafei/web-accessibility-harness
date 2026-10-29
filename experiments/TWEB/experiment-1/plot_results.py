"""Regenerate the repeatability figure using this experiment's exported CSVs."""
import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True
PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent))

from plotting.evidence import bind_inputs, read_csv, save_manifest
from plotting.repeatability import plot

FIGURES = {
    'repeatability-alignment': (4, 'fig:repeatability-alignment'),
}


def load_rows():
    rows = read_csv(PACKAGE, 'runs.csv')
    for row in rows:
        row['repeat'] = int(row['repeat'])
        for field in ('axe', 'lighthouse'):
            row[field] = float(row[field])
        row['failed'] = {name: int(row[name.lower() + '_failures'])
                         for name in ('Syntactic', 'Semantic', 'Layout')}
    blocks = {(row['domain'], row['policy'], row['repeat']) for row in rows}
    domains = {row['domain'] for row in rows}
    expected = {(domain, policy, repeat) for domain in domains
                for policy in ('P1', 'P2') for repeat in (1, 2, 3)}
    if len(domains) != 5 or len(rows) != 30 or blocks != expected:
        raise ValueError('Expected five sources, two policies and three repetitions')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=PACKAGE.parent / 'plots')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = bind_inputs(PACKAGE, ('runs.csv',))
    rows = load_rows()
    plot(rows, output)
    statistics = {'selected_runs': 30,
                  'endpoints': [{key: row[key] for key in
                                 ('domain', 'policy', 'repeat', 'axe', 'lighthouse', 'failed')}
                                for row in rows],
                  'range_definition': 'Maximum minus minimum within each source/policy group.'}
    save_manifest(PACKAGE, output, inputs, FIGURES, statistics)


if __name__ == '__main__':
    main()
