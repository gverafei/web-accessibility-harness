"""Serve measured remediation documents with their exact captured resources."""
import hashlib
import json
import re
from pathlib import Path

from flask import Response, current_app, redirect, url_for
from dataset_navigation import serve_dataset_file
from harness.contracts import ContractError, digest
from harness.environment import Environment
from harness.saved_resource_references import (
    saved_consent_controls, saved_image_variants, saved_stylesheet_references,
)
from harness.observed_state import prepare, presentation_signature
from harness.store import Store

VERSION = 'measured-remediation-navigation-v3'


def measured_page(run_id, filename, dataset_root):
    root = Path(dataset_root).resolve()
    directory = root / 'remediations' / str(run_id)
    path = (directory / filename).resolve()
    if path.parent != directory or path.suffix.lower() != '.html' or not path.is_file():
        return None
    store = Store(current_app.config.get('HARNESS_ROOT'))
    try:
        page = store.get(f'sql-run-{run_id}-page')
    except KeyError:
        return None
    raw = path.read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    artifacts = [page['data']['original_id']]
    artifacts.extend(row['data']['source_id'] for row in store.list('attempt', page['campaign'])
                     if row['data'].get('run_id') == f'sql-run-{run_id}')
    if not any(store.get(ident)['data']['sha256'] == source_hash for ident in artifacts):
        raise ContractError('This document differs from the measured remediation evidence')
    capture = store.get(page['data']['capture_id'])
    adapter_signature = presentation_signature()
    token = digest({'version': VERSION, 'source_sha256': source_hash,
                    'capture_sha256': capture['hash'], 'run_id': run_id,
                    'presentation_sha256': adapter_signature})
    target = directory / '.saved' / token
    receipt = target / 'navigation.json'
    with store.named_lock('remediation-navigation-' + token):
        if not receipt.is_file():
            source, styles = saved_stylesheet_references(raw.decode('utf-8'), capture)
            source, images = saved_image_variants(source, capture)
            source, controls = saved_consent_controls(source)
            source, observed = prepare(source, capture)
            base = url_for('remediation.saved_candidate_file', run_id=run_id,
                           token=token, filename='page.html').rsplit('/', 1)[0] + '/'
            _, transport = Environment(store, datasets=target).replay(
                capture, source, 'page', base_url=base)
            files = target / capture['id']
            receipt.write_text(json.dumps({
                'version': VERSION, 'source_sha256': source_hash,
                'presentation_sha256': adapter_signature,
                'source_filename': path.name,
                'capture_id': capture['id'], 'capture_sha256': capture['hash'],
                'directory': capture['id'],
                'page_sha256': hashlib.sha256((files / 'page.html').read_bytes()).hexdigest(),
                'transport': transport, 'stylesheet_reference_adjustments': styles,
                'image_variant_adjustments': images, 'local_control_adapters': controls,
                'observed_presentation_adapters': observed,
            }), encoding='utf-8')
    return redirect(url_for('remediation.saved_candidate_file', run_id=run_id,
                            token=token, filename='page.html'))


def saved_file(run_id, token, filename, dataset_root):
    if not re.fullmatch(r'[a-f0-9]{64}', token):
        return Response(status=404)
    if filename != 'page.html' and not re.fullmatch(r'assets/[a-f0-9]{64}', filename):
        return Response(status=404)
    root = Path(dataset_root).resolve()
    target = root / 'remediations' / str(run_id) / '.saved' / token
    receipt = target / 'navigation.json'
    if not receipt.is_file():
        return Response(status=404)
    info = json.loads(receipt.read_text())
    if filename == 'page.html' and (info.get('version') != VERSION
                                  or info.get('presentation_sha256') != presentation_signature()):
        directory = root / 'remediations' / str(run_id)
        for source in directory.glob('*.html'):
            if hashlib.sha256(source.read_bytes()).hexdigest() == info['source_sha256']:
                return redirect(url_for('remediation.dataset_page', run_id=run_id,
                                        filename=source.name))
        return Response(status=409)
    files = (target / info['directory']).resolve()
    if not files.is_relative_to(target.resolve()):
        return Response(status=404)
    return serve_dataset_file(files, filename, root,
        expected_sha256=info['page_sha256'] if filename == 'page.html' else None,
        anonymous_resource=filename.startswith('assets/'))
