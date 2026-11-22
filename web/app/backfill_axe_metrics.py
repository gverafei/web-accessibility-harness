"""Populate separated legacy counts from existing evidence, without re-evaluation."""
import json
import hashlib
from pathlib import Path

from axe_metrics import raw_metrics, persist_metrics


def iteration_evidence(row, root=Path('/results/raw')):
    if row.get('axe_raw_path'):
        path = Path(row['axe_raw_path'])
        if path.is_file(): return path
    directory = root / f"experiment_remediation_{row['run_id']}_{row['iteration_number']}"
    matches = []
    # Evaluator artifact names retain the SHA-256 of the submitted URL even if
    # the page redirects. Do not guess from the redirected raw.url or basename.
    submitted_digest = hashlib.sha256(str(row.get('output_url') or '').encode()).hexdigest()[:16]
    for path in sorted(directory.glob('*_axe.json')):
        try: raw = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError): continue
        matched_url = raw.get('url') == row.get('output_url')
        matched_artifact = path.name.endswith('_' + submitted_digest + '_axe.json')
        if matched_url or matched_artifact: matches.append(path)
    return matches[0] if len(matches) == 1 else None


def backfill(cursor, apply=False, root=Path('/results/raw')):
    report = {'iterations': 0, 'members': 0, 'unresolved_iterations': [], 'unresolved_members': []}
    resolved = {}
    cursor.execute('SELECT id,run_id,iteration_number,output_url,axe_raw_path FROM remediation_iterations WHERE axe_wcag_violations IS NULL')
    for row in cursor.fetchall():
        path = iteration_evidence(row, root)
        if not path:
            report['unresolved_iterations'].append(row['id']); continue
        try: metrics = raw_metrics(path)
        except (OSError, ValueError, KeyError, TypeError):
            report['unresolved_iterations'].append(row['id']); continue
        if apply: persist_metrics(cursor, 'remediation_iterations', row['id'], metrics, str(path))
        resolved[row['id']] = path
        report['iterations'] += 1
    cursor.execute('''SELECT m.id,m.source_result_id,m.source_remediation_iteration_id,
        r.axe_raw_path source_raw,ri.axe_raw_path candidate_raw
        FROM comparison_members m
        LEFT JOIN experiment_results r ON r.id=m.source_result_id
        LEFT JOIN remediation_iterations ri ON ri.id=m.source_remediation_iteration_id
        WHERE m.axe_wcag_violations IS NULL''')
    for row in cursor.fetchall():
        path = row.get('candidate_raw') if row.get('source_remediation_iteration_id') else row.get('source_raw')
        path = path or resolved.get(row.get('source_remediation_iteration_id'))
        try: metrics = raw_metrics(path) if path else None
        except (OSError, ValueError, KeyError, TypeError): metrics = None
        if metrics is None:
            report['unresolved_members'].append(row['id']); continue
        if apply: persist_metrics(cursor, 'comparison_members', row['id'], metrics)
        report['members'] += 1
    return report


if __name__ == '__main__':
    import argparse
    from flask import Flask
    from config import Config
    from database import get_connection
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    app = Flask(__name__); app.config.from_object(Config)
    with app.app_context():
        connection = get_connection(); cursor = connection.cursor(dictionary=True)
        try:
            report = backfill(cursor, apply=args.apply)
            if args.apply: connection.commit()
            print(json.dumps(report))
        except Exception:
            connection.rollback(); raise
        finally:
            cursor.close(); connection.close()
