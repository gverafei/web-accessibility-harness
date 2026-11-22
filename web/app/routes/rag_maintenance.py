from flask import Blueprint, abort, jsonify, render_template, request, url_for
from flask_babel import gettext as _
import requests
from rag_sync_jobs import SyncConflict, enqueue, view
import rag_examples
from rag_corpus import read_json

rag_maintenance_bp = Blueprint('rag_maintenance', __name__, url_prefix='/rag-act')


@rag_maintenance_bp.get('')
@rag_maintenance_bp.get('/examples/<identity>')
def examples(identity=None):
    if identity is not None:
        try:
            from uuid import UUID
            UUID(identity)
        except ValueError:
            abort(404)
    collection = None
    data = item = None
    error, status_code = None, 200
    metadata = {}
    try:
        collection = rag_examples.collection_for_read(request.args.get('collection'))
        if identity:
            item = rag_examples.example(collection, identity)
            if item is None:
                abort(404)
        else:
            data = rag_examples.page_view(rag_examples.metadata_rows(collection), request.args)
        manifest = read_json('corpus.json')
        if manifest.get('collection') == collection:
            metadata = manifest
    except rag_examples.CorpusChanged:
        error, status_code = _('The active corpus changed. Reload the example browser.'), 409
    except (requests.RequestException, OSError, ValueError, KeyError, TypeError):
        error, status_code = _('Could not load saved examples. Check the vector database and try again.'), 503
    filters = {key:request.args.get(key, '') for key in ('q','source','outcome','size','page')}
    def browse_url(page=None):
        values = dict(filters)
        if data:
            values.update(q=data['q'], source=data['source'], outcome=data['outcome'],
                          size=data['size'], page=data['page'])
        if page is not None:
            values['page'] = page
        return url_for('rag_maintenance.examples', collection=collection, **values)
    return render_template('rag_examples.html', data=data, item=item, collection=collection,
                           metadata=metadata, error=error, browse_url=browse_url,
                           safe_url=rag_examples.safe_url, filters=filters,
                           is_detail=identity is not None), status_code


@rag_maintenance_bp.get('/status')
def status():
    try:
        return jsonify(view())
    except (OSError, ValueError):
        return jsonify(error=_('Could not load synchronization status. Try again.')), 503


@rag_maintenance_bp.post('/synchronize')
def synchronize():
    if not request.is_json:
        return jsonify(error=_('Send a JSON maintenance request.')), 400
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error=_('Send a JSON maintenance request.')), 400
    try:
        job = enqueue(data.get('mode'), confirmed=data.get('confirmed') is True)
    except SyncConflict as exc:
        return jsonify(error=_(str(exc))), 409
    except ValueError as exc:
        return jsonify(error=_(str(exc))), 400
    except (requests.RequestException, OSError, KeyError):
        return jsonify(error=_('Could not request synchronization. Check the vector database and shared storage.')), 503
    return jsonify(job=job), 202
