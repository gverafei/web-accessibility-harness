"""Ephemeral readiness signal for native downloads; never buffers file bodies."""
import re

from flask import request
from werkzeug.exceptions import HTTPException


def signal_download_ready(response):
    token = request.args.get('_download_token')
    if token is None and request.method == 'POST' and request.endpoint == 'remediation.export_runs':
        try:
            token = request.form.get('_download_token')
        except HTTPException:
            # Preserve the original upload/malformed-request error, not a 500.
            return response
    if not token or not re.fullmatch(r'[a-f0-9]{32}', token):
        return response
    disposition = response.headers.get('Content-Disposition', '').lower()
    ready = 200 <= response.status_code < 300 and disposition.startswith('attachment')
    response.set_cookie(f'warp_download_{token}', 'ready' if ready else 'error',
                        max_age=60, path='/', samesite='Lax', secure=request.is_secure)
    response.headers['Cache-Control'] = 'no-store'
    return response
