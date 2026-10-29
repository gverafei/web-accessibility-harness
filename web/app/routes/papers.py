"""Explicitly published reviewer PDFs, kept outside the code and review stores."""
from pathlib import Path

from flask import Blueprint, abort, current_app, send_file


papers_bp = Blueprint('papers', __name__, url_prefix='/papers')
PAPERS = (
    {'key': 'harness', 'label': 'Harness - ACM TWEB'},
    {'key': 'verification-method', 'label': 'Verification Method - MethodX'},
    {'key': 'dataset', 'label': 'Dataset - MDPI Data'},
)


@papers_bp.app_context_processor
def paper_navigation():
    return {'reviewer_papers': PAPERS}


@papers_bp.get('/<key>.pdf')
def document(key):
    if key not in {paper['key'] for paper in PAPERS}:
        abort(404)
    root = Path(current_app.config['PAPER_DOCUMENT_ROOT']).resolve()
    path = (root / (key + '.pdf')).resolve()
    if path.parent != root or not path.is_file():
        abort(404)
    response = send_file(path, mimetype='application/pdf', conditional=True,
                         download_name=key + '.pdf', max_age=0)
    # Stable links revalidate after a published file update.
    response.headers['Cache-Control'] = 'private, no-cache'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
