"""Standard-library verification and deterministic output provenance for review bundles."""
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs(root):
    root = Path(root)
    manifest = json.loads((root / 'MANIFEST.json').read_text())
    for name, expected in manifest['files'].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file() or sha(path) != expected:
            raise ValueError('Hash mismatch: ' + name)
    return manifest


def record_outputs(root, names, script, record_ids, append=False):
    root = Path(root)
    manifest = verify_inputs(root)
    previous = json.loads((root / 'PROVENANCE.json').read_text()) if append else {'outputs': {}}
    scripts = {name: value for name, value in manifest['files'].items()
               if name.endswith('.py') or name in ('records.json', 'consumption.json') or name.startswith('protocol/')}
    for name in names:
        previous['outputs'][name] = {'sha256': sha(root / name), 'script': script,
                                     'script_sha256': sha(root / script), 'record_ids': sorted(record_ids)}
    previous.update(schema='a11yharness/1', campaign_id=manifest['campaign_id'],
                    campaign_hash=manifest['manifest_hash'], input_hashes=scripts,
                    protocol=manifest.get('protocol_bundle'), manifest_sha256=sha(root / 'MANIFEST.json'))
    (root / 'PROVENANCE.json').write_text(json.dumps(previous, sort_keys=True, indent=2, allow_nan=False))
