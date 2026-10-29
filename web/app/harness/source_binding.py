"""Validate an explicit frozen input and its same-source admitted reference audit."""
import hashlib
from .contracts import ContractError, digest

VERSION = 'frozen-admitted-source-binding-v1'


def resolve(store, binding, source_id, evaluator_runtime):
    if binding is None:
        return None
    if not isinstance(binding, dict) or binding.get('version') != VERSION:
        raise ContractError('Invalid frozen source binding')
    if binding.get('sql_source_id') != source_id:
        raise ContractError('Frozen source binding belongs to another acquisition')
    if binding.get('evaluator_runtime_sha256') != digest(evaluator_runtime):
        raise ContractError('Frozen source binding evaluator changed')
    capture = store.get(binding['capture_id'])
    audit = store.get(binding['audit_id'])
    check = store.get(binding['replay_id'])
    source_id = binding['source_artifact_id']
    raw = store.read_blob(source_id)
    if (capture['kind'] != 'capture' or audit['kind'] != 'audit' or
            check['kind'] != 'replay_admission' or
            capture['data'].get('replay_source_id') != source_id or
            capture['data'].get('package_sha256') != binding['native_package_sha256'] or
            hashlib.sha256(raw).hexdigest() != binding['input_sha256'] or
            audit['data'].get('status') != 'completed' or
            check['data'].get('status') != 'admitted' or
            check['data'].get('audit_id') != audit['id'] or
            check['data'].get('capture_id') != capture['id']):
        raise ContractError('Frozen source binding evidence mismatch')
    # The source bytes are fixed. Reference DOM artifacts remain unmodified,
    # including transient media identifiers and their captured resource evidence.
    rendered = store.read_blob(audit['data']['artifacts']['rendered'])
    if hashlib.sha256(rendered).hexdigest() != binding['reference_document_sha256']:
        raise ContractError('Frozen reference document mismatch')
    from copy import deepcopy
    from .syntax_policy import localize
    localized=deepcopy(audit)
    if audit['data'].get('syntax')is not None:
        localized['data']['syntax']=localize(audit['data']['syntax'],raw.decode('utf-8'),capture['data'].get('captured_url',''))
    return {'capture': capture, 'baseline': localized, 'check': check,
            'source': raw.decode('utf-8'), 'identity': 'bound-source-' + digest(binding)}
