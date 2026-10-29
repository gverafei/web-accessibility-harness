"""Shared UI proxy for stored pages; dataset-server remains internal."""
from pathlib import Path
from urllib.parse import quote
import hashlib
import requests
from flask import Response, has_request_context, request
from werkzeug.http import parse_range_header


def isolated_page(response):
    response.headers['Content-Security-Policy'] = (
        'sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox')
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def serve_dataset_file(directory, filename, dataset_root, expected_sha256=None,
                       anonymous_resource=False):
    directory, dataset_root = Path(directory).resolve(), Path(dataset_root).resolve()
    path = (directory / filename).resolve()
    if (directory not in path.parents or not directory.is_relative_to(dataset_root)
            or not path.is_file()):
        return Response(status=404)
    if expected_sha256 and hashlib.sha256(path.read_bytes()).hexdigest()!=expected_sha256:
        return Response(status=409)
    relative = path.relative_to(dataset_root).as_posix()
    try:
        upstream = requests.get('http://dataset-server:8080/' + quote(relative, safe='/'),
                                timeout=15, allow_redirects=False)
    except requests.RequestException:
        return Response(status=502)
    if upstream.status_code != 200:
        return Response(status=404 if upstream.status_code == 404 else 502)
    if expected_sha256 and hashlib.sha256(upstream.content).hexdigest()!=expected_sha256:
        return Response(status=409)
    content_type = upstream.headers.get('Content-Type', 'application/octet-stream')
    media_type = content_type.split(';', 1)[0].strip().lower()
    if ('charset=' not in content_type.lower().replace(' ', '')
            and (media_type.startswith('text/') or media_type in (
                'application/xhtml+xml', 'application/javascript', 'image/svg+xml'))):
        # Replay exports are UTF-8, but the static server omits charset. Without
        # it, HTML without a meta declaration can be interpreted as Windows-1252,
        # corrupting ordinary text and CSS icon glyphs. Preserve explicit or
        # non-UTF-8 encodings and serve the recorded bytes without rewriting.
        try:
            upstream.content.decode('utf-8')
        except UnicodeDecodeError:
            pass
        else:
            content_type += '; charset=utf-8'
    response = Response(upstream.content, content_type=content_type)
    if media_type.startswith(('video/', 'audio/')):
        # The internal static server may return the complete saved entity even
        # when a browser requests a byte range. Slice that same entity locally.
        total = len(upstream.content)
        response.headers['Accept-Ranges'] = 'bytes'
        range_value = request.headers.get('Range') if has_request_context() else None
        if range_value:
            parsed = parse_range_header(range_value)
            bounds = parsed.range_for_length(total) if parsed and parsed.units == 'bytes' else None
            if bounds is None:
                response = Response(status=416)
                response.headers['Content-Range'] = f'bytes */{total}'
            else:
                start, end = bounds
                response = Response(upstream.content[start:end], status=206, content_type=content_type)
                response.headers['Content-Range'] = f'bytes {start}-{end-1}/{total}'
            response.headers['Accept-Ranges'] = 'bytes'
    response.headers['Cache-Control'] = 'no-store'
    resolved_parts = path.relative_to(directory).parts
    if anonymous_resource and len(resolved_parts) > 1 and resolved_parts[0] == 'assets':
        # A sandboxed page has an opaque origin. Its retained public assets
        # (not Harness pages or session data) must permit anonymous font/module reads.
        response.headers['Access-Control-Allow-Origin'] = '*'
    return isolated_page(response)
