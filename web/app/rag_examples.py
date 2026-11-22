"""Read-only inspection of the published corpus, never execution of example HTML."""
from urllib.parse import urlsplit
from uuid import UUID

import requests

from rag_corpus import active_collection
from remediation_rag import COLLECTION, QDRANT_URL

METADATA = ['source', 'source_kind', 'rule_id', 'rule_name', 'testcase_id',
            'title', 'expected', 'requirements']
PAGE_SIZES = (5, 10, 20, 25, 50, 100, 250, 500)


class CorpusChanged(ValueError):
    pass


def collection_for_read(requested=None):
    collection = active_collection(COLLECTION)
    if requested and requested != collection:
        raise CorpusChanged('The active corpus changed. Reload the example browser.')
    return collection


def safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ('https', 'http') and parsed.hostname and not parsed.username:
            return value
    except ValueError:
        pass
    return None


def metadata_rows(collection):
    rows, cursors = [], set()
    offset = None
    # Keep each HTTP request bounded; reject excessive/malformed pagination,
    # rather than silently showing only part of the corpus as the total.
    for _ in range(20):
        body = {'limit':1000, 'with_payload':METADATA, 'with_vector':False}
        if offset is not None:
            body['offset'] = offset
        response = requests.post(f'{QDRANT_URL}/collections/{collection}/points/scroll',
                                 json=body, timeout=3)
        if response.status_code == 404 and offset is None:
            return []
        response.raise_for_status()
        data = response.json()['result']
        for point in data['points']:
            item = dict(point.get('payload') or {})
            item['id'] = str(UUID(str(point['id'])))
            item['official'] = item.get('source') == 'W3C ACT Rules'
            item['complementary'] = item.get('source_kind') == 'curated_guidance'
            rows.append(item)
        offset = data.get('next_page_offset')
        if offset is None:
            return sorted(rows, key=lambda item: (
                str(item.get('rule_name') or '').casefold(),
                str(item.get('title') or '').casefold(), item['id']))
        marker = str(offset)
        if marker in cursors:
            raise ValueError('Repeated corpus pagination cursor')
        cursors.add(marker)
    raise ValueError('Corpus pagination exceeds the inspection limit')


def example(collection, identity):
    identity = str(UUID(identity))
    response = requests.get(f'{QDRANT_URL}/collections/{collection}/points/{identity}',
                            params={'with_payload':'true', 'with_vector':'false'}, timeout=3)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    point = response.json()['result']
    if not point:
        return None
    return {**(point.get('payload') or {}), 'id':identity}


def page_view(rows, args):
    query = args.get('q', '').strip()[:200]
    source = args.get('source', '')
    outcome = args.get('outcome', '')
    source = source if source in ('official', 'complementary') else ''
    outcome = outcome if outcome in ('passed', 'failed') else ''
    try:
        size = int(args.get('size', 5))
        page = max(1, int(args.get('page', 1)))
    except (ValueError, TypeError):
        size, page = 5, 1
    size = size if size in PAGE_SIZES else 5
    matches = []
    for item in rows:
        if source and not item.get(source):
            continue
        if outcome and item.get('expected') != outcome:
            continue
        searchable = ' '.join(str(item.get(key) or '') for key in
            ('id','rule_id','rule_name','testcase_id','title','requirements')).casefold()
        if query.casefold() in searchable:
            matches.append(item)
    pages = max(1, (len(matches)+size-1)//size)
    page = min(page, pages)
    official = [item for item in rows if item['official']]
    return {'rows':matches[(page-1)*size:page*size], 'total':len(rows),
            'official':len(official), 'complementary':sum(item['complementary'] for item in rows),
            'official_rules':len({item.get('rule_id') for item in official if item.get('rule_id')}),
            'matched':len(matches), 'page':page, 'pages':pages, 'size':size,
            'q':query, 'source':source, 'outcome':outcome, 'sizes':PAGE_SIZES}
