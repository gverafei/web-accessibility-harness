"""Regenerate experimental paper figures from the checked-in CSV evidence."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=int, choices=(1, 2, 3, 4), nargs='+',
                        default=(1, 2, 3, 4), help='Select experiments; defaults to all four.')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'plots',
                        help='Directory for the numbered figures; defaults to TWEB/plots.')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='harness-plot-cache-') as cache:
        env = dict(os.environ, MPLCONFIGDIR=cache, PYTHONDONTWRITEBYTECODE='1')
        for number in dict.fromkeys(args.experiment):
            package = ROOT / f'experiment-{number}'
            command = [sys.executable, str(package / 'plot_results.py'),
                       '--output-dir', str(args.output_dir.resolve())]
            subprocess.run(command, check=True, env=env)


if __name__ == '__main__':
    main()
