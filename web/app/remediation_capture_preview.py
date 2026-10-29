"""Source-bound refreshed display captures; canonical measurements stay immutable."""
import hashlib
import json
from pathlib import Path


def _manifest(directory):
    metadata = json.loads((Path(directory) / '.capture-previews.json').read_text())
    if not isinstance(metadata, dict) or metadata.get('version') != 'local-capture-preview-v1':
        return {}
    entries = metadata.get('iterations')
    return entries if isinstance(entries, dict) else {}


def _refreshed_image(item, results_root):
    root = Path(results_root).resolve()
    path = (root / item['path']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return None
    if hashlib.sha256(path.read_bytes()).hexdigest() != item['capture_sha256']:
        return None
    return path


def refreshed_capture(directory, iteration_id, source_path, original_path, results_root):
    try:
        item = _manifest(directory)[str(iteration_id)]
        for file, expected in ((source_path, item['source_sha256']),
                               (original_path, item['original_capture_sha256'])):
            if hashlib.sha256(Path(file).read_bytes()).hexdigest() != expected:
                return None
        return _refreshed_image(item, results_root)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def refreshed_evidence_capture(directory, source_bytes, original_bytes, results_root):
    """Match immutable review evidence, independent of presentation numbering."""
    try:
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        original_hash = hashlib.sha256(original_bytes).hexdigest()
        matches = [item for item in _manifest(directory).values()
                   if isinstance(item, dict) and item.get('source_sha256') == source_hash
                   and item.get('original_capture_sha256') == original_hash]
        if len(matches) != 1:
            return None
        return _refreshed_image(matches[0], results_root)
    except (OSError, ValueError, KeyError, TypeError):
        return None
