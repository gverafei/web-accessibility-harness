"""Exact-evidence reuse, never a vote or model/worker-dependent comparison."""
from harness.contracts import digest

VERSION = 'exact-evidence-judgment-cache-v1'


def key(model, criterion, evidence, images=()):
    return 'taxonomy-judgment-' + digest({'version': VERSION, 'model': model,
        'criterion': criterion, 'evidence': evidence, 'images': list(images)})


def lookup(store, ident):
    try:
        saved = store.get(ident)
        return saved['data']['answer'], saved['id']
    except KeyError:
        return None, None


def save(store, providers, ident, answer, parent):
    with store.named_lock(ident):
        cached, reference = lookup(store, ident)
        if reference:
            return reference
        return store.append('taxonomy_judgment_cache', {'version': VERSION,
            'answer': answer, 'parent_judgment_id': parent}, providers.campaign, ident)['id']
