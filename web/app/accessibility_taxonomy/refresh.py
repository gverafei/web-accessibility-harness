"""Replace active measurements only after reassessing the same frozen documents."""
from copy import deepcopy
from harness.contracts import ContractError
from .assessment import VERSION


def refreshed_outcome(outcome, measurement, store):
    old=outcome.get('taxonomy_measurement') or {}
    if measurement.get('version')!=VERSION or measurement.get('status')!='completed' or measurement.get('errors'):
        raise ContractError('Replacement requires completed current instrument measurement')
    for phase in ('original','retained'):
        before=store.get(old[phase+'_assessment_id'])['data']
        after=store.get(measurement[phase+'_assessment_id'])['data']
        if (before['audit_id']!=after['audit_id'] or before['document_sha256']!=after['document_sha256']):
            raise ContractError('Reassessment must use the same original and retained documents')
    updated=deepcopy(outcome)
    updated['taxonomy_measurement']=deepcopy(measurement)
    return updated
