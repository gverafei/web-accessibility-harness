"""Explicit instrument amendments validated against an unchanged source reference."""
from .contracts import ContractError


def validate(store, campaign, revision_id, current):
    revision = store.get(revision_id)
    data = revision['data']
    previous = store.get(campaign + '-evaluator-runtime')['data']
    binding = store.get(campaign)['data'].get('frozen_source_binding') or {}
    before = store.get(data['reference_audit_id'])['data']
    after = store.get(data['calibration_audit_id'])['data']
    if (revision['kind'] != 'evaluator_recovery_revision'
            or revision['campaign'] != campaign
            or data['previous_runtime'] != {k:v for k,v in previous.items() if k != 'schema'}
            or data['runtime'] != current or data['document_modified'] is not False
            or (binding and data['reference_audit_id'] != binding['audit_id'])
            or before.get('status') != 'completed' or after.get('status') != 'completed'
            or any(before.get(k) != after.get(k) for k in ('axe', 'lighthouse'))
            or before['replay']['input_document_sha256'] != after['replay']['input_document_sha256']):
        raise ContractError('Instrument recovery requires an unchanged, score-matched source calibration')
    return data['previous_runtime']


def authorize(store, campaign, runtime, reference_audit_id, calibration_audit_id, reason):
    if not reason.strip():
        raise ContractError('Instrument recovery requires a recorded reason')
    previous = store.get(campaign + '-evaluator-runtime')['data']
    revision = store.append('evaluator_recovery_revision', {
        'previous_runtime': {k:v for k,v in previous.items() if k != 'schema'},
        'runtime': runtime, 'reference_audit_id': reference_audit_id,
        'calibration_audit_id': calibration_audit_id, 'document_modified': False,
        'reason': reason, 'generation_repeated': False,
    }, campaign)
    validate(store, campaign, revision['id'], runtime)
    return revision
