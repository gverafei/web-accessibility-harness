"""Explicit eligibility of one frozen input, separate from automatic judgments."""
import hashlib

from .contracts import ContractError, digest


def evidence(store, campaign, verification):
    binding = campaign['data'].get('frozen_source_binding')
    data = verification['data']
    if (not binding or verification['kind'] != 'evidence_verification'
            or data.get('phase') != 'baseline'
            or data.get('status') not in ('rejected', 'review_required')
            or data.get('capture_id') != binding['capture_id']
            or data.get('audit_id') != binding['audit_id']
            or data.get('deterministic_id') != binding['replay_id']):
        raise ContractError('Source eligibility requires the exact frozen baseline judgment')
    capture = store.get(binding['capture_id'])
    audit = store.get(binding['audit_id'])
    replay = store.get(binding['replay_id'])
    if (capture['kind'] != 'capture' or audit['kind'] != 'audit'
            or replay['kind'] != 'replay_admission'
            or audit['data'].get('status') != 'completed'
            or replay['data'].get('status') != 'admitted'
            or replay['data'].get('capture_id') != capture['id']
            or replay['data'].get('audit_id') != audit['id']
            or capture['data'].get('package_sha256') != binding['native_package_sha256']
            or hashlib.sha256(store.read_blob(audit['data']['artifacts']['rendered'])).hexdigest()
                != binding['reference_document_sha256']
            or capture['data'].get('replay_source_id') != binding['source_artifact_id']
            or hashlib.sha256(store.read_blob(binding['source_artifact_id'])).hexdigest()
                != binding['input_sha256']):
        raise ContractError('Source eligibility cannot bypass deterministic input checks')
    refs = data.get('evidence_refs')
    if not isinstance(refs, list) or len(refs) != 2:
        raise ContractError('Source eligibility requires both saved visual references')
    return {'frozen_source_binding': binding, 'verification_id': verification['id'],
            'verification_hash': verification['hash'],
            'visual_evidence': [{'id': ident, 'sha256': hashlib.sha256(store.read_blob(ident)).hexdigest()}
                                for ident in refs]}


def approve(store, campaign_id, run_id, verification_id, reference):
    """Called only by an explicit administrative decision, never by a model."""
    campaign = store.get(campaign_id)
    if (campaign['kind'] != 'campaign' or not reference.strip()
            or store.checkpoint(run_id)[0]
            or any(store.list(kind, campaign_id) for kind in ('page', 'run', 'attempt', 'run_result'))):
        raise ContractError('Source eligibility must be recorded before repair starts')
    binding = evidence(store, campaign, store.get(verification_id))
    return store.append('source_admission', {
        **binding, 'campaign_id': campaign_id, 'run_id': run_id,
        'authority': 'interactive_user', 'reference': reference,
        'scope': 'frozen-input-eligibility-only', 'status': 'admitted',
        'automatic_judgment_modified': False, 'human_review_created': False,
    }, campaign_id, 'source-admission-' + digest({'run': run_id, 'evidence': binding}))


def validate(store, campaign, run_id, admission_id, verification_id=None):
    record = store.get(admission_id)
    data = record['data']
    verification = store.get(verification_id or data['verification_id'])
    expected = evidence(store, campaign, verification)
    if (record['kind'] != 'source_admission' or record['campaign'] != campaign['id']
            or data.get('campaign_id') != campaign['id'] or data.get('run_id') != run_id
            or data.get('authority') != 'interactive_user' or not data.get('reference')
            or data.get('scope') != 'frozen-input-eligibility-only'
            or data.get('status') != 'admitted'
            or data.get('automatic_judgment_modified') is not False
            or data.get('human_review_created') is not False
            or any(data.get(key) != value for key, value in expected.items())):
        raise ContractError('Source eligibility does not match this frozen input and run')
    return record
