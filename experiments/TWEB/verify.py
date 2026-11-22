"""Verify the exported experimental packages without services or model calls."""

import argparse
import collections
import csv
import hashlib
import json
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EXPECTED = {1: (5, 30, 116), 2: (30, 450, 1074),
            3: (1, 12, 20), 4: (30, 30, None)}
PLOT_COUNTS = {1: 1, 2: 5, 3: 1, 4: 4}


def read_rows(folder, name):
    with (folder / 'data' / name).open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def run_id(value):
    return str(value).removeprefix('sql-run-')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify_files(folder):
    manifest = json.loads((folder / 'data/checksums.json').read_text())
    require(manifest['algorithm'].lower().replace('-', '') == 'sha256',
            'Unsupported checksum algorithm')
    for relative, expected in manifest['files'].items():
        path = (folder / relative).resolve()
        require(folder in path.parents, f'Path outside package: {relative}')
        require(path.is_file(), f'Missing file: {relative}')
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        require(actual == expected, f'Checksum mismatch: {relative}')
    return len(manifest['files'])


def verify_plots(folder, number):
    """Detect stale figures after an evidence or plotting-code change."""
    folder = Path(folder).resolve()
    output = folder.parent / 'plots'
    manifest = json.loads((output / f'metadata/experiment-{number}.json').read_text())
    require(manifest['format_version'] == 3 and manifest['experiment'] == number
            and manifest['input_package'] == folder.name,
            'Unexpected figure manifest')
    require(len(manifest['figures']) == PLOT_COUNTS[number],
            'Incomplete experimental figures')
    for group in ('inputs', 'code'):
        base = folder if group == 'inputs' else folder.parent
        for relative, expected in manifest[group].items():
            path = (base / relative).resolve()
            require(base in path.parents, f'Path outside evidence package: {relative}')
            require(path.is_file(), f'Missing figure input or script: {relative}')
            require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                    f'Stale figure {group} binding: {relative}')
    for figure in manifest['figures']:
        path = (output / figure['file']).resolve()
        require(output in path.parents, 'Figure path outside plots folder')
        require(path.name.startswith(f'figure-{figure["figure_number"]:02d}-'),
                'Figure filename does not match its article number')
        require(path.is_file(), f'Missing figure: {figure["file"]}')
        require(hashlib.sha256(path.read_bytes()).hexdigest() == figure['sha256'],
                f'Figure checksum mismatch: {figure["file"]}')
        require(figure['width_px'] >= 7000
                and min(figure['metadata_dpi']) >= 1000,
                f'Insufficient figure resolution: {figure["file"]}')
    return len(manifest['figures'])


def verify_adaptive_comparison(folder, sources, runs, iterations):
    source_hashes = {row['domain']: row['input_sha256'] for row in sources}
    require(len(source_hashes) == 30, 'Expected thirty distinct adaptive sources')
    fixed = read_rows(folder, 'fixed-conditions.csv')
    blocks = collections.Counter((row['domain'], row['policy']) for row in fixed)
    require(set(blocks) == {(domain, f'P{policy}') for domain in source_hashes
                            for policy in range(5)}, 'Incomplete fixed comparison')
    require(all(count == 3 for count in blocks.values()),
            'Expected three fixed configurations per source and policy')
    for row in runs + fixed:
        require(source_hashes.get(row['domain']) == row['input_sha256'],
                f'Frozen source mismatch: {row["domain"]}')
    measured = collections.defaultdict(list)
    for row in iterations:
        measured[run_id(row['run_id'])].append(row)
    for row in runs:
        versions = measured[run_id(row['run_id'])]
        indices = [int(version['candidate_index']) for version in versions]
        require(indices == list(range(1, len(versions) + 1)),
                f'Nonsequential measured versions: run {row["run_id"]}')
        chosen = next(version for version in versions
                      if version['chosen'].lower() in {'true', '1'})
        require(all(float(row[key]) == float(chosen[key])
                    for key in ('axe', 'lighthouse')),
                f'Selected measurements differ: run {row["run_id"]}')
    accounting = read_rows(folder, 'accounting.csv')
    by_run = {run_id(row['run_id']): row for row in runs}
    require(len(accounting) == len(runs)
            and {run_id(row['run_id']) for row in accounting} == set(by_run),
            'Incomplete run accounting')
    for row in accounting:
        outcome = by_run[run_id(row['run_id'])]
        require(abs(Decimal(row['published_cost_usd'])
                    - Decimal(row['included_receipt_cost_usd'])) < Decimal('0.0000001'),
                f'Unreconciled cost: run {row["run_id"]}')
        require(abs(Decimal(row['published_cost_usd'])
                    - Decimal(outcome['cost_usd'])) < Decimal('0.0000001'),
                f'Cost differs from selected execution: run {row["run_id"]}')
        require(all(int(row['published_' + key]) == int(outcome[key])
                    for key in ('input_tokens', 'output_tokens')),
                f'Tokens differ from selected execution: run {row["run_id"]}')
        require(abs(float(row['operational_seconds']) - float(outcome['seconds'])) < 1e-8,
                f'Execution duration differs: run {row["run_id"]}')
    totals = read_rows(folder, 'task-accounting.csv')
    for key in ('input_tokens', 'output_tokens'):
        require(sum(int(row[key]) for row in runs)
                == sum(int(row[key]) for row in totals), f'Incomplete {key} accounting')
    require(abs(sum(Decimal(row['cost_usd']) for row in runs)
                - sum(Decimal(row['cost_usd']) for row in totals)) < Decimal('0.0000001'),
            'Task and run costs differ')


def verify_experiment(number):
    folder = (ROOT / f'experiment-{number}').resolve()
    checked = verify_files(folder)
    sources = read_rows(folder, 'sources.csv')
    runs = read_rows(folder, 'runs.csv')
    iterations = read_rows(folder, 'iterations.csv')
    actual = (len(sources), len(runs), len(iterations))
    expected = EXPECTED[number]
    if expected[2] is None:
        protocol = json.loads((folder / 'data/protocol.json').read_text())
        expected = (*expected[:2], int(protocol['evaluated_versions']))
    require(actual == expected, f'Unexpected cohort counts: {actual}')
    members = {run_id(row['run_id']) for row in runs}
    require(len(members) == len(runs), 'Duplicate run identifiers')
    versions = collections.Counter()
    chosen = collections.Counter()
    for row in iterations:
        identity = run_id(row['run_id'])
        require(identity in members, f'Unknown iteration run: {identity}')
        versions[identity] += 1
        if row['chosen'].lower() in {'true', '1'}:
            chosen[identity] += 1
    for row in runs:
        identity = run_id(row['run_id'])
        recorded = (row.get('evaluated_versions') or row.get('evaluated_candidates')
                    or row.get('iterations'))
        require(versions[identity] == int(recorded),
                f'Version count mismatch: run {identity}')
        require(chosen[identity] == 1, f'Expected one chosen version: run {identity}')
        require(float(row['axe']) >= 0, f'Negative Axe count: run {identity}')
        require(0 <= float(row['lighthouse']) <= 100,
                f'Lighthouse score outside range: run {identity}')
        for field in ('text_percent', 'links_percent', 'images_percent',
                      'content_retention'):
            if row.get(field):
                require(0 <= float(row[field]) <= 100.000001,
                        f'Retention outside range: {field}, run {identity}')
    if number == 4 and (folder / 'data/task-accounting.csv').exists():
        verify_adaptive_comparison(folder, sources, runs, iterations)
    figures = verify_plots(folder, number)
    return {'experiment': number, 'sources': actual[0], 'runs': actual[1],
            'evaluated_versions': actual[2], 'verified_files': checked,
            'verified_figures': figures}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=int, choices=EXPECTED,
                        help='Verify one experiment instead of all four.')
    args = parser.parse_args()
    numbers = [args.experiment] if args.experiment else EXPECTED
    for number in numbers:
        print(json.dumps(verify_experiment(number)))


if __name__ == '__main__':
    main()
