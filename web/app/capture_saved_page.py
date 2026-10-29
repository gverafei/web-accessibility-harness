"""Navigate a saved acquisition using only its hash-bound captured resources."""
import hashlib
import json
import re
from pathlib import Path

from flask import Response, current_app, redirect, url_for
from dataset_navigation import serve_dataset_file
from harness.contracts import digest
from harness.environment import Environment
from harness.observed_state import prepare, presentation_signature
from harness.saved_resource_references import saved_image_variants, saved_stylesheet_references
from harness.store import Store

VERSION = 'saved-capture-navigation-v2'
RESULTS_ROOT = Path('/results/raw')


def bound_capture(store, row, results_root=None):
    rendered = Path(row.get('source_snapshot_path') or '')
    screenshot = Path(row.get('screenshot_path') or '')
    root = Path(results_root or RESULTS_ROOT).resolve()
    if any(not path.resolve().is_relative_to(root) or not path.is_file()
           for path in (rendered, screenshot)):
        return None
    rendered_hash = hashlib.sha256(rendered.read_bytes()).hexdigest()
    image_hash = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    with store.connect() as database:
        records = database.execute("SELECT * FROM records WHERE kind='capture' "
            "AND json_extract(payload,'$.screenshot_path')=? ORDER BY created DESC,id DESC",
            (str(screenshot),)).fetchall()
    for record in records:
        capture = store.unpack(record)
        data = capture['data']
        if data.get('captured_url') != (row.get('captured_url') or row.get('url')):
            continue
        try:
            if (hashlib.sha256(store.read_blob(data['rendered_id'])).hexdigest() == rendered_hash
                    and hashlib.sha256(store.read_blob(data['screenshot_id'])).hexdigest() == image_hash):
                return capture
        except (KeyError, FileNotFoundError):
            continue
    return None


def page_response(row, dataset_root):
    store = Store(current_app.config.get('HARNESS_ROOT'))
    capture = bound_capture(store, row)
    if capture is None:
        return Response('No matching saved resource package is available.', status=404)
    source_bytes = store.read_blob(capture['data']['replay_source_id'])
    adapter_signature = presentation_signature()
    token = digest({'version': VERSION, 'capture': capture['hash'],
                    'source': hashlib.sha256(source_bytes).hexdigest(), 'result_id': row['id'],
                    'presentation_sha256': adapter_signature})
    target = Path(dataset_root) / 'captures' / str(row['id']) / '.saved' / token
    receipt = target / 'navigation.json'
    with store.named_lock('capture-navigation-' + token):
        if not receipt.is_file():
            source, styles = saved_stylesheet_references(source_bytes.decode('utf-8'), capture)
            source, images = saved_image_variants(source, capture)
            source, observed = prepare(source, capture)
            base = url_for('experiments.saved_source_file', experiment_id=row['experiment_id'],
                           result_id=row['id'], token=token, filename='page.html').rsplit('/',1)[0]+'/'
            Environment(store, datasets=target).replay(capture, source, 'page', base_url=base)
            page = target / capture['id'] / 'page.html'
            receipt.write_text(json.dumps({'version': VERSION, 'experiment_id': row['experiment_id'],
                'presentation_sha256': adapter_signature,
                'capture_id': capture['id'], 'capture_sha256': capture['hash'],
                'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
                'page_sha256': hashlib.sha256(page.read_bytes()).hexdigest(),
                'stylesheet_adjustments': styles, 'image_adjustments': images,
                'observed_presentation_adapters': observed}), encoding='utf-8')
    return redirect(url_for('experiments.saved_source_file', experiment_id=row['experiment_id'],
                            result_id=row['id'], token=token, filename='page.html'))


def saved_file(experiment_id, result_id, token, filename, dataset_root):
    if not re.fullmatch(r'[a-f0-9]{64}', token) or not re.fullmatch(r'page\.html|assets/[a-f0-9]{64}', filename):
        return Response(status=404)
    root = Path(dataset_root).resolve()
    target = root / 'captures' / str(result_id) / '.saved' / token
    receipt = target / 'navigation.json'
    if not receipt.is_file():
        return Response(status=404)
    info = json.loads(receipt.read_text())
    files = (target / info['capture_id']).resolve()
    if (info.get('version') not in ('saved-capture-navigation-v1', VERSION) or info.get('experiment_id') != experiment_id
            or not files.is_relative_to(target.resolve())):
        return Response(status=404)
    if filename == 'page.html' and (info['version'] != VERSION
                                  or info.get('presentation_sha256') != presentation_signature()):
        return redirect(url_for('experiments.source_page', experiment_id=experiment_id, result_id=result_id))
    return serve_dataset_file(files, filename, root,
        expected_sha256=info['page_sha256'] if filename == 'page.html' else None,
        anonymous_resource=filename.startswith('assets/'))
