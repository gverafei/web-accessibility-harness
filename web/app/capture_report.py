"""Present saved acquisition measurements without generating new assessments."""
import json
from pathlib import Path


def read_report(filename, root=Path('/results/raw')):
    path = Path(filename or '')
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def visual_verdict(store, result_id):
    with store.connect() as database:
        cases = [store.unpack(row) for row in database.execute(
            "SELECT * FROM records WHERE kind='verification_case' "
            "AND json_extract(payload,'$.application')='acquisition' "
            "AND json_extract(payload,'$.source_id')=? ORDER BY created DESC,id DESC", (result_id,))]
    retired = {row['campaign'] for row in store.list('verification_retirement')}
    excluded = {case for row in store.list('verification_exclusion') for case in row['data'].get('case_ids', [])}
    for case in cases:
        if case['campaign'] in retired or case['id'] in excluded:
            continue
        data = case['data']
        try:
            judgment = store.get(data['verification_id'])
        except KeyError:
            continue
        expected = {binding['id']:binding['hash'] for binding in data.get('bindings', [])}
        value = judgment['data']
        if (judgment['kind'] == 'evidence_verification' and value.get('phase') == 'baseline'
                and expected.get(judgment['id']) == judgment['hash']
                and value.get('capture_id') == data.get('capture_id')
                and value.get('audit_id') == data.get('audit_id')):
            return {'status':value.get('status'), 'rationale':value.get('rationale','')}
    return None


def details(rows, catalogue=None):
    store = None
    if catalogue and (Path(catalogue) / 'catalogue.sqlite3').is_file():
        from harness.store import Store
        store = Store(catalogue)
    for row in rows:
        axe = read_report(row.get('axe_raw_path'))
        lighthouse = read_report(row.get('lighthouse_raw_path'))
        findings = []
        for violation in axe.get('violations', []):
            if not any(tag.startswith('wcag') for tag in violation.get('tags', [])):
                continue
            findings.append({'rule':violation.get('id'), 'description':violation.get('help') or violation.get('description'),
                'impact':violation.get('impact'), 'instances':len(violation.get('nodes', [])),
                'criteria':[tag[4]+'.'+tag[5]+'.'+tag[6:] for tag in violation.get('tags', [])
                            if tag.startswith('wcag') and tag[4:].isdigit() and len(tag)>=7]})
        audits = lighthouse.get('audits', {})
        accessibility_ids = {entry['id'] for entry in lighthouse.get('categories', {}).get('accessibility', {}).get('auditRefs', [])}
        lighthouse_findings = [item for item in audits.values()
            if item.get('score') == 0 and item.get('scoreDisplayMode') not in ('notApplicable','manual')
            and item.get('id') in accessibility_ids]
        row['report'] = {'axe_findings':findings, 'lighthouse_findings':lighthouse_findings,
                         'visual':visual_verdict(store, row['id']) if store else None}
    completed = [row for row in rows if row.get('status') == 'completed']
    axe_values = [row['axe_wcag_violations'] for row in completed if row.get('axe_wcag_violations') is not None]
    lighthouse_values = [row['lighthouse_score'] for row in completed if row.get('lighthouse_score') is not None]
    return {'completed':len(completed), 'total':len(rows), 'axe_instances':sum(axe_values) if axe_values else None,
            'lighthouse_mean':sum(lighthouse_values)/len(lighthouse_values) if lighthouse_values else None,
            'seconds':sum(float(row.get('execution_seconds') or 0) for row in rows)}
