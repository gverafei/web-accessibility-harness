import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DATASET_ROOT = Path("/datasets").resolve()
ISOLATED_CSP = (
    "default-src 'self' data: blob:; "
    "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; "
    "media-src 'self' data: blob:; connect-src 'none'; "
    "frame-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'"
)


def resource_csp(root, request_path):
    # Frozen harness evidence always stays isolated. Original acquisitions retain
    # their declared resource policy so dynamic legacy pages render as before.
    from urllib.parse import unquote, urlsplit
    parts = [p for p in unquote(urlsplit(request_path).path).split('/') if p]
    if not parts or parts[0] == 'harness':
        return ISOLATED_CSP
    metadata = (root / parts[0] / '.warp-dataset.json').resolve()
    if not metadata.is_relative_to(root.resolve()):
        return ISOLATED_CSP
    try:
        policy = json.loads(metadata.read_text(encoding='utf-8')).get('resource_policy')
    except (OSError, ValueError, TypeError, AttributeError):
        policy = 'isolated'
    if policy == 'external':
        return None
    return ISOLATED_CSP.replace("script-src 'self' 'unsafe-inline'", "script-src 'self'").replace("connect-src 'none'", "connect-src 'self'")


class DatasetHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DATASET_ROOT), **kwargs)

    def guess_type(self, path):
        target=Path(path)
        try:
            types=json.loads((target.parent / '.content-types.json').read_text(encoding='utf-8'))
            if target.name in types: return types[target.name]
        except (OSError,ValueError,TypeError): pass
        return super().guess_type(path)

    def end_headers(self):
        policy = resource_csp(DATASET_ROOT, self.path)
        if policy:
            self.send_header('Content-Security-Policy', policy)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        super().end_headers()

    def log_message(self, _format, *_args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), DatasetHandler).serve_forever()
