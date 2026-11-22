"""Portable terminal-run evidence; no generation, evaluator or worker calls.

IDs and historical strings are provenance. Only explicitly linked artifact paths
and serving URLs are relocated; prompts/responses and evidence bytes stay intact.
"""
import hashlib
import json
import re
import shutil
import stat
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from result_portability import ARTIFACT_COLUMNS, json_value, normalize_url
from warp_export import CHUNK_BYTES

TERMINAL = frozenset({'accepted', 'completed_with_warnings', 'failed', 'stopped'})
MAX_FILES = 100_000
MAX_MANIFEST = 64 * 1024**2
MAX_EVIDENCE = 32 * 1024**3
TABLES = frozenset({'experiments', 'experiment_results', 'experiment_environment',
                   'tranco_samples', 'remediation_runs', 'remediation_iterations',
                   'remediation_events', 'remediation_templates'})


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _json_row(row):
    return {key: json_value(value) for key, value in row.items()}


def _paths(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _paths(child)
    elif isinstance(value, list):
        for child in value:
            yield from _paths(child)
    elif isinstance(value, str) and value.startswith(('/results/raw/', '/datasets/')):
        yield value


def export_manifest(cursor, run_ids, exported_at, raw_root='/results/raw', dataset_root='/datasets'):
    ids = sorted(set(int(value) for value in run_ids))
    if not ids or len(ids) > 1000 or any(value <= 0 for value in ids):
        raise ValueError('Select between 1 and 1,000 completed remediation runs.')
    cursor.execute('SELECT * FROM remediation_runs WHERE id IN (' + ','.join(['%s'] * len(ids)) + ') ORDER BY id', ids)
    runs = cursor.fetchall()
    if len(runs) != len(ids) or any(row['status'] not in TERMINAL for row in runs):
        raise ValueError('Only existing, terminal remediation runs can be exported.')
    raw = Path(raw_root).resolve()
    datasets = Path(dataset_root).resolve()
    files, members, missing = [], [], []
    seen = set()

    def add(path, owner, relative=None, required=False):
        if not path:
            return
        path = Path(path)
        resolved = path.resolve()
        key = (owner, str(path))
        if key in seen:
            if required and not any(row['owner'] == owner and row['path'] == str(path) for row in files):
                raise ValueError('A required frozen HTML/candidate file is unavailable: ' + path.name)
            return
        seen.add(key)
        if path.is_symlink() or not resolved.is_file() or not (raw in resolved.parents or datasets in resolved.parents):
            if required:
                raise ValueError('A required frozen HTML/candidate file is unavailable: ' + path.name)
            missing.append({'owner': owner, 'path': str(path)})
            return
        relative = relative or f'evidence/{len(files)}/{path.name}'
        name = f'artifacts/{len(files)}/{path.name}'
        files.append({'owner': owner, 'path': str(path), 'relative': relative,
                      'member': name, 'size': resolved.stat().st_size,
                      'sha256': digest_file(resolved)})
        members.append((resolved, name))

    sources, experiments, templates, packages = {}, {}, {}, []
    for run in runs:
        source_id, experiment_id = run['source_result_id'], None
        if source_id not in sources:
            cursor.execute('SELECT * FROM experiment_results WHERE id=%s', (source_id,))
            source = cursor.fetchone()
            if not source:
                raise ValueError('The original observation is unavailable.')
            experiment_id = source['experiment_id']
            # Frozen HTML is essential. Optional legacy evidence can be absent.
            if not source.get('source_snapshot_path'):
                raise ValueError('The original rendered HTML is unavailable.')
            for column in ARTIFACT_COLUMNS:
                add(source.get(column), f'source:{source_id}', required=column == 'source_snapshot_path')
            sources[source_id] = _json_row(source)
            if experiment_id not in experiments:
                cursor.execute('SELECT * FROM experiments WHERE id=%s', (experiment_id,))
                metadata = cursor.fetchone()
                cursor.execute('SELECT * FROM experiment_environment WHERE experiment_id=%s ORDER BY id', (experiment_id,))
                environments = cursor.fetchall()
                cursor.execute('SELECT * FROM tranco_samples WHERE experiment_id=%s', (experiment_id,))
                sample = cursor.fetchone()
                experiments[experiment_id] = {'data': _json_row(metadata),
                    'environment': [_json_row(row) for row in environments],
                    'tranco_sample': _json_row(sample) if sample else None}
        if run.get('template_id') and run['template_id'] not in templates:
            cursor.execute('SELECT * FROM remediation_templates WHERE id=%s', (run['template_id'],))
            template = cursor.fetchone()
            if template:
                templates[run['template_id']] = _json_row(template)
        cursor.execute('SELECT * FROM remediation_iterations WHERE run_id=%s ORDER BY iteration_number', (run['id'],))
        iterations = cursor.fetchall()
        cursor.execute('SELECT * FROM remediation_events WHERE run_id=%s ORDER BY id', (run['id'],))
        events = cursor.fetchall()
        owner = f'run:{run["id"]}'
        directory = datasets / 'remediations' / str(run['id'])
        if directory.is_dir():
            for path in sorted(directory.rglob('*')):
                if path.is_file():
                    add(path, owner, 'candidates/' + path.relative_to(directory).as_posix())
        for iteration in iterations:
            add(iteration.get('output_path'), owner, required=bool(iteration.get('output_path')))
            # Raw evaluator files live beside the screenshot/Axe report; bundle
            # that bounded directory, including Lighthouse/WAVE if available.
            parents = set()
            for column in ('screenshot_path', 'axe_raw_path'):
                path = iteration.get(column)
                add(path, owner)
                if path and raw in Path(path).resolve().parents:
                    parents.add(Path(path).parent)
            for parent in sorted(parents):
                for path in sorted(parent.glob('*')):
                    if path.is_file():
                        add(path, owner)
            for key, value in iteration.items():
                if key.endswith('_json') and value:
                    for path in _paths(json.loads(value) if isinstance(value, str) else value):
                        add(path, owner)
        packages.append({'data': _json_row(run), 'iterations': [_json_row(row) for row in iterations],
                         'events': [_json_row(row) for row in events]})
    manifest = {'format': 'warp-remediations', 'version': 1, 'exported_at': exported_at,
                'sources': list(sources.values()), 'experiments': list(experiments.values()),
                'templates': list(templates.values()), 'runs': packages,
                'files': files, 'missing_optional_files': missing}
    if sum(row['size'] for row in files) > MAX_EVIDENCE or len(files) > MAX_FILES:
        raise ValueError('The selected evidence exceeds the package limits. Export smaller batches.')
    if len(json.dumps(manifest, default=json_value).encode()) > MAX_MANIFEST:
        raise ValueError('The manifest exceeds 64 MiB. Export a smaller batch.')
    return manifest, members


def _safe_relative(value):
    return isinstance(value, str) and bool(value) and not value.startswith('/') and '\\' not in value and all(part not in ('', '.', '..') for part in value.split('/'))


def _rows(values, label):
    if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
        raise ValueError('Invalid ' + label)
    ids = [row.get('id') for row in values]
    if any(type(value) is not int or value <= 0 for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Invalid/duplicate ' + label + ' IDs')
    return {row['id']: row for row in values}


def validate_package(package):
    """Validate structure, all references and binary hashes before persistence."""
    infos = package.infolist()
    names = [item.filename for item in infos]
    if len(names) != len(set(names)) or len(names) > MAX_FILES + 1 or any(not _safe_relative(name) for name in names):
        raise ValueError('Invalid archive paths or duplicate members.')
    if any(item.is_dir() or item.flag_bits & 1 or stat.S_ISLNK(item.external_attr >> 16) for item in infos):
        raise ValueError('Directories, encrypted members and symlinks are not supported.')
    info = package.getinfo('remediation.json')
    if info.file_size > MAX_MANIFEST:
        raise ValueError('The manifest exceeds 64 MiB.')
    payload = json.loads(package.read(info))
    if not isinstance(payload, dict) or payload.get('format') != 'warp-remediations' or type(payload.get('version')) is not int or payload.get('version') != 1:
        raise ValueError('Unsupported remediation package.')
    sources = _rows(payload.get('sources'), 'sources')
    experiments = _rows([entry['data'] for entry in payload.get('experiments', [])], 'experiments')
    templates = _rows(payload.get('templates'), 'templates')
    runs = _rows([entry['data'] for entry in payload.get('runs', [])], 'runs')
    if not runs or len(runs) > 1000 or not sources:
        raise ValueError('Empty or oversized remediation selection.')
    owners = {f'source:{key}' for key in sources} | {f'run:{key}' for key in runs}
    for source in sources.values():
        parsed = urlsplit(str(source.get('url') or ''))
        if source.get('experiment_id') not in experiments or parsed.scheme not in {'http', 'https'} or not parsed.hostname:
            raise ValueError('Invalid source observation.')
    for entry in payload['experiments']:
        _rows(entry.get('environment', []), 'environments')
        if any(row.get('experiment_id') != entry['data']['id'] for row in entry.get('environment', [])):
            raise ValueError('Invalid environment link.')
        sample = entry.get('tranco_sample')
        if sample is not None and (not isinstance(sample, dict) or sample.get('experiment_id') != entry['data']['id']):
            raise ValueError('Invalid Tranco provenance.')
    required = {(f'source:{row["id"]}', row.get('source_snapshot_path')) for row in sources.values()}
    for entry in payload['runs']:
        run = entry['data']
        if run.get('status') not in TERMINAL or run.get('source_result_id') not in sources or (run.get('template_id') and run['template_id'] not in templates):
            raise ValueError('Invalid run status or source/template link.')
        iterations = _rows(entry.get('iterations'), 'iterations')
        _rows(entry.get('events'), 'events')
        numbers = [row.get('iteration_number') for row in iterations.values()]
        if any(type(number) is not int or number <= 0 for number in numbers) or len(set(numbers)) != len(numbers):
            raise ValueError('Invalid iteration order.')
        if any(row.get('run_id') != run['id'] for row in [*iterations.values(), *entry['events']]):
            raise ValueError('A child belongs to a different run.')
        if run.get('accepted_iteration_id') and run['accepted_iteration_id'] not in iterations:
            raise ValueError('Invalid retained-candidate link.')
        if run['status'] == 'accepted' and not run.get('accepted_iteration_id'):
            raise ValueError('An accepted run must retain a candidate.')
        for row in iterations.values():
            if row.get('output_path'):
                required.add((f'run:{run["id"]}', row['output_path']))
        if run.get('accepted_iteration_id') and not iterations[run['accepted_iteration_id']].get('output_path'):
            raise ValueError('The retained candidate has no HTML.')
    files = payload.get('files')
    if not isinstance(files, list) or any(not isinstance(row, dict) for row in files):
        raise ValueError('Invalid file inventory.')
    seen, destinations, pointers, total = {'remediation.json'}, set(), set(), 0
    for row in files:
        name, relative, owner = row.get('member'), row.get('relative'), row.get('owner')
        if owner not in owners or not _safe_relative(name) or not name.startswith('artifacts/') or not _safe_relative(relative):
            raise ValueError('Invalid artifact owner or path.')
        pointer = (owner, row.get('path'))
        if not isinstance(row.get('path'), str) or name in seen or pointer in pointers or (owner, relative) in destinations:
            raise ValueError('Duplicate artifact link/destination.')
        seen.add(name); pointers.add(pointer); destinations.add((owner, relative))
        size = row.get('size')
        if type(size) is not int or size < 0 or not re.fullmatch(r'[a-f0-9]{64}', str(row.get('sha256') or '')):
            raise ValueError('Invalid artifact size/digest.')
        total += size
        member = package.getinfo(name)
        if member.file_size != size or total > MAX_EVIDENCE:
            raise ValueError('Artifact size exceeds the declared limit.')
        digest = hashlib.sha256()
        with package.open(member) as source:
            while chunk := source.read(CHUNK_BYTES):
                digest.update(chunk)
        if digest.hexdigest() != row['sha256']:
            raise ValueError('Artifact SHA-256 does not match: ' + PurePosixPath(name).name)
    if seen != set(names) or not required.issubset(pointers):
        raise ValueError('Missing required evidence or unexpected archive members.')
    # Candidate download/preview routes only serve this run's dataset directory.
    for entry in payload['runs']:
        for row in entry['iterations']:
            if row.get('output_path'):
                file = next(file for file in files if (file['owner'], file['path']) == (f'run:{entry["data"]["id"]}', row['output_path']))
                if not file['relative'].startswith('candidates/'):
                    raise ValueError('A candidate must belong to its run directory.')
    missing = payload.get('missing_optional_files', [])
    if not isinstance(missing, list) or any(not isinstance(row, dict) or row.get('owner') not in owners or not isinstance(row.get('path'), str) for row in missing):
        raise ValueError('Invalid missing-file inventory.')
    return payload


def _insert(cursor, table, row, excluded=()):
    if table not in TABLES:
        raise ValueError('Unsupported destination table.')
    cursor.execute('SHOW COLUMNS FROM ' + table)
    allowed = {item['Field'] if isinstance(item, dict) else item[0] for item in cursor.fetchall()}
    data = {key: value for key, value in row.items() if key in allowed and key not in {'id', *excluded}}
    columns = ','.join('`' + key + '`' for key in data)
    values = [json.dumps(value, default=json_value) if isinstance(value, (dict, list)) else value for value in data.values()]
    cursor.execute(f'INSERT INTO {table} ({columns}) VALUES ({",".join(["%s"] * len(data))})', values)
    return cursor.lastrowid


def _relocate_json(value, mapping):
    """Only path/url fields are live links; other historical text is immutable."""
    if isinstance(value, list):
        return [_relocate_json(child, mapping) for child in value]
    if isinstance(value, dict):
        return {key: mapping.get(child, child) if isinstance(child, str) and (key == 'path' or key.endswith(('_path', '_url'))) else _relocate_json(child, mapping)
                for key, child in value.items()}
    return value


def import_package(conn, package, payload, imported_at, title='', raw_root='/results/raw', dataset_root='/datasets'):
    """Payload must have passed validate_package. One transaction, new IDs only."""
    cursor = conn.cursor(dictionary=True)
    created, mapping, run_map, source_map, experiment_map, template_map = [], {}, {}, {}, {}, {}
    provenance_digest = hashlib.sha256(package.read('remediation.json')).hexdigest()
    try:
        for entry in payload['experiments']:
            old = entry['data']
            rows = [row for row in payload['sources'] if row['experiment_id'] == old['id']]
            restored = dict(old, title=(title or old['title'])[:240] + ' (import)',
                urls='\n'.join(row['url'] for row in rows), status='completed',
                experiment_origin='imported', dataset_id=None, reuse_cached_results=False,
                resume_count=0, last_resumed_at=None)
            new = _insert(cursor, 'experiments', restored)
            experiment_map[old['id']] = new
            directory = Path(raw_root) / f'experiment_{new}'
            directory.mkdir(exist_ok=False); created.append(directory)
            for row in rows:
                mapping[f'source:{row["id"]}'] = directory / f'source_{row["id"]}'
            for environment in entry.get('environment', []):
                _insert(cursor, 'experiment_environment', dict(environment, experiment_id=new))
            if entry.get('tranco_sample'):
                _insert(cursor, 'tranco_samples', dict(entry['tranco_sample'], experiment_id=new))
        for old in payload['templates']:
            template_map[old['id']] = _insert(cursor, 'remediation_templates', dict(old, is_builtin=False))
        for row in payload['sources']:
            data = dict(row, experiment_id=experiment_map[row['experiment_id']],
                dataset_observation_id=None, source_result_id=None, source_experiment_id=None,
                provenance='imported', normalized_url=normalize_url(row['url']), cost_incurred_usd=0)
            for column in ARTIFACT_COLUMNS:
                data[column] = None
            source_map[row['id']] = _insert(cursor, 'experiment_results', data)
        for entry in payload['runs']:
            old = entry['data']
            provenance = {'format': payload['format'], 'version': 1, 'manifest_sha256': provenance_digest,
                'imported_at': str(imported_at), 'exported_at': payload.get('exported_at'),
                'source_run_id': old['id'], 'source_result_id': old['source_result_id'],
                'prior_import': old.get('import_provenance_json'),
                'missing_optional_files': [item for item in payload.get('missing_optional_files', [])
                                           if item.get('owner') in {f'run:{old["id"]}', f'source:{old["source_result_id"]}'}]}
            restored = dict(old, source_result_id=source_map[old['source_result_id']],
                template_id=template_map.get(old.get('template_id')), accepted_iteration_id=None,
                published_experiment_id=None, import_provenance_json=provenance,
                title=(title or old['title'])[:180])
            new = _insert(cursor, 'remediation_runs', restored)
            run_map[old['id']] = new
            directory = Path(dataset_root) / 'remediations' / str(new)
            directory.mkdir(parents=True, exist_ok=False); created.append(directory)
            mapping[f'run:{old["id"]}'] = directory
        file_map = {}
        for row in payload['files']:
            # Inventory destinations are relative to a fresh, exclusive directory.
            root = mapping[row['owner']]
            relative = row['relative']
            if row['owner'].startswith('run:') and relative.startswith('candidates/'):
                relative = relative[len('candidates/'):]
            elif row['owner'].startswith('run:'):
                run_id = run_map[int(row['owner'].split(':')[1])]
                root = Path(raw_root) / f'experiment_remediation_{run_id}_import'
                if root not in created:
                    root.mkdir(exist_ok=False); created.append(root)
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with package.open(row['member']) as source, path.open('xb') as destination:
                shutil.copyfileobj(source, destination, CHUNK_BYTES)
            file_map[(row['owner'], row['path'])] = str(path)
        for row in payload['sources']:
            paths = {column: file_map.get((f'source:{row["id"]}', row.get(column))) for column in ARTIFACT_COLUMNS}
            cursor.execute('UPDATE experiment_results SET ' + ','.join(f'{key}=%s' for key in paths) + ' WHERE id=%s', [*paths.values(), source_map[row['id']]])
        imported_ids = []
        for entry in payload['runs']:
            old, iteration_map = entry['data'], {}
            new = run_map[old['id']]
            scoped = {path: target for (owner, path), target in file_map.items()
                      if owner in {f'run:{old["id"]}', f'source:{old["source_result_id"]}'}}
            for row in entry['iterations']:
                restored = dict(row, run_id=new)
                for column in ('output_path', 'screenshot_path', 'axe_raw_path'):
                    restored[column] = scoped.get(row.get(column))
                if restored.get('output_path'):
                    relative = Path(restored['output_path']).relative_to(Path(dataset_root)).as_posix()
                    restored['output_url'] = 'http://dataset-server:8080/' + relative
                    scoped[row.get('output_url')] = restored['output_url']
                else:
                    restored['output_url'] = None
                for key in row:
                    if key.endswith('_json') and row[key]:
                        value = json.loads(row[key]) if isinstance(row[key], str) else row[key]
                        restored[key] = _relocate_json(value, scoped)
                iteration_map[row['id']] = _insert(cursor, 'remediation_iterations', restored)
            for row in entry['events']:
                # Event text/details are historical records, never live foreign IDs.
                _insert(cursor, 'remediation_events', dict(row, run_id=new))
            retained = iteration_map.get(old.get('accepted_iteration_id'))
            cursor.execute('UPDATE remediation_runs SET accepted_iteration_id=%s WHERE id=%s', (retained, new))
            imported_ids.append(new)
        conn.commit()
        return imported_ids
    except Exception:
        conn.rollback()
        for directory in reversed(created):
            shutil.rmtree(directory)
        raise
    finally:
        cursor.close()
