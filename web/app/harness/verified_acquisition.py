"""Acquisition-only adapter over native capture, replay, repeat and review contracts.

No RAG corpus, repair worker, remediation run or SQL observation is required.
Automated admission leaves human verification explicitly pending.
"""
import copy
import requests
from urllib.parse import urlsplit
from .contracts import ContractError, budget, digest, number, object_value, public_url, text
from .decision_models import snapshot as decision_snapshot
from .preparation import budget_group, compatible_groups, protocol_bundle
from .providers import BudgetStop, Ledger, UncertainCall

VERSION = 'verified-acquisition-only-v2'


def _existing(store, ident):
    try:
        return store.get(ident)
    except KeyError:
        return None


def freeze(store, value, evaluator_runtime, ident):
    """Register an explicit queue and its own budget; never visit or call a model."""
    value = copy.deepcopy(object_value(value, 'acquisition configuration'))
    allowed = {'name', 'study_id', 'seed', 'authorization_reference', 'campaign_cost_limit',
               'budget_group', 'capture_verifier', 'category_review_model', 'repair_budget',
               'review_budget', 'candidates', 'protocol_bundle', 'evaluator', 'partition'}
    if set(value) - allowed:
        raise ContractError('Acquisition-only configuration cannot enable remediation')
    candidates = value.get('candidates')
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 1000:
        raise ContractError('Freeze an explicit bounded candidate queue')
    for candidate in candidates:
        object_value(candidate, 'candidate')
        text(candidate.get('candidate_id'), 'candidate identifier')
        candidate['url'] = public_url(candidate.get('url'))
    if (len({c['candidate_id'] for c in candidates}) != len(candidates)
            or len({c['url'] for c in candidates}) != len(candidates)):
        raise ContractError('Candidate identifiers and URLs must be unique')
    group = budget_group(value.get('budget_group'))
    ceiling = number(value.get('campaign_cost_limit'), 'acquisition ceiling', 0, 1000000)
    if not group or ceiling > min(group['total_usd'], group['stage_limits'][group['stage']]):
        raise ContractError('Use an approved acquisition budget and cumulative ceiling')
    for campaign in store.list('campaign'):
        old = campaign['data'].get('budget_group')
        if old and old['id'] == group['id'] and not compatible_groups(old, group):
            raise ContractError('Shared acquisition budget limits cannot change')
    models = {key: decision_snapshot(value.get(key))
              for key in ('capture_verifier', 'category_review_model')}
    if not models['capture_verifier'].get('vision'):
        raise ContractError('Capture verification requires a vision-capable Decisions model')
    if any(model['model'] != 'openai/gpt-6-luna-decisions' for model in models.values()):
        raise ContractError('This acquisition protocol freezes Luna Decisions')
    limits = {key: budget(value.get(key)) for key in ('repair_budget', 'review_budget')}
    if any(item['max_cost_usd'] > ceiling for item in limits.values()):
        raise ContractError('Acquisition account limits must fit the cumulative ceiling')
    standard = (value.get('evaluator') or {}).get('axe_standard', 'wcag22aa')
    if standard not in ('wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'):
        raise ContractError('Unknown Axe profile')
    partition = value.get('partition', 'development')
    if partition not in ('development', 'validation', 'test'):
        raise ContractError('Unknown acquisition partition')
    if not isinstance(evaluator_runtime, dict) or not evaluator_runtime.get('source_files'):
        raise ContractError('Freeze the observed evaluator runtime before acquisition')
    from .versions import snapshot
    manifest = {key: text(value.get(key), key) for key in
                ('name', 'study_id', 'seed', 'authorization_reference')}
    manifest.update(acquisition_protocol=VERSION, candidates=candidates,
        source={'kind': 'urls', 'urls': [c['url'] for c in candidates], 'count': len(candidates)},
        budget_group=group, campaign_cost_limit=ceiling, **models, **limits,
        evaluator={'axe_standard': standard}, runtime_snapshot=snapshot(),
        evaluator_runtime_sha256=digest(evaluator_runtime), partition=partition,
        capture_only=True, workers=[], conditions=[], repetitions=1,
        evaluation_basis='verified-acquisition-pending-human', analysis={'contrasts': []},
        protocol_bundle=protocol_bundle(value.get('protocol_bundle')))
    manifest['digest'] = digest(manifest)
    row = store.append('campaign', manifest, ident=ident)
    store.append('evaluator_snapshot', evaluator_runtime, ident, ident + '-evaluator-runtime')
    if not store.checkpoint(ident)[0]:
        store.checkpoint(ident, {'status': 'externally_managed', 'stage': 'acquisition', 'pages': [], 'runs': []})
    return row


def _native_reference(capture):
    reference = capture['data'].get('native_control_reference')
    if (not isinstance(reference, dict) or reference.get('version') != 'observed-native-control-state-v1'
            or not isinstance(reference.get('records'), list)):
        raise ContractError('Observed native control state is unavailable')


def _capture_admission(store, capture, campaign):
    from .capture_admission import assess
    ident = 'acquisition-admission-' + digest({'capture': capture['id'], 'version': VERSION})
    previous = _existing(store, ident)
    if previous:
        return previous
    source = store.read_blob(capture['data']['rendered_id']).decode()
    return store.append('capture_admission', assess(source, capture['data']) |
        {'capture_id': capture['id'], 'source_id': capture['data']['rendered_id']}, campaign, ident)


def _reference(store, environment, capture, campaign, identity, config):
    source = store.read_blob(capture['data']['replay_source_id']).decode()
    audit = _existing(store, identity + '-audit') or environment.audit(capture, source, campaign, identity + '-audit', config)
    if audit['data'].get('status') != 'completed':
        raise ContractError('Baseline measurement is incomplete; retained for review')
    check = _existing(store, identity + '-replay') or environment.replay_check(capture, source, campaign, identity + '-replay', audit)
    from .source_recovery import recover
    return recover(store, environment, capture, source, audit, check, campaign, identity, config)


def _repeat(store, environment, capture, source, audit, check, campaign, identity, config):
    from .source_repeatability import verify
    from .source_recovery import recover
    if check['data'].get('status') != 'admitted':
        raise ContractError('Frozen replay rejected: ' + str(check['data'].get('reasons')))
    repeated = verify(store, environment, capture, source, audit, campaign, config)
    if repeated['data']['status'] != 'admitted':
        rejected = store.append('replay_admission', {**check['data'], 'status': 'rejected',
            'reasons': list(dict.fromkeys(check['data'].get('reasons', []) + repeated['data']['reasons'])),
            'repeatability_id': repeated['id']}, campaign, identity + '-repeatability-replay')
        capture, source, audit, check = recover(store, environment, capture, source, audit, rejected, campaign, identity, config)
        repeated = verify(store, environment, capture, source, audit, campaign, config)
    if check['data'].get('status') != 'admitted' or repeated['data']['status'] != 'admitted':
        raise ContractError('Frozen source measurements are not repeatable; retained before inference')
    return capture, source, audit, check, repeated


def acquire(store, environment, providers, campaign, index):
    """Attempt exactly one frozen candidate; reuse its durable outcome on resume."""
    manifest, cid = campaign['data'], campaign['id']
    if manifest.get('acquisition_protocol') != VERSION:
        raise ContractError('Unknown acquisition protocol')
    if type(index) is not int or not 0 <= index < len(manifest['candidates']):
        raise ContractError('Candidate is outside the frozen queue')
    from .versions import snapshot
    if manifest['runtime_snapshot'] != snapshot():
        raise ContractError('Acquisition runtime changed; preserve evidence and review an amendment')
    if providers.campaign != cid:
        raise ContractError('Provider belongs to another campaign')
    environment.verify_runtime(cid)
    from .pausing import check as check_pause
    check_pause(store, cid)
    calls = Ledger(store).rows(cid)
    if any(call['cost_status'] == 'unknown' or call['status'] == 'dispatching' for call in calls):
        raise UncertainCall('Resolve uncertain acquisition consumption before another attempt')
    identity = cid + '-candidate-' + str(index)
    with store.named_lock(identity):
        previous = _existing(store, identity + '-outcome')
        if previous:
            return previous
        candidate = manifest['candidates'][index]
        store.append('execution_authorization', {'campaign_id': cid,
            'manifest_hash': campaign['hash'], 'authorization_reference': manifest['authorization_reference'],
            'scope': 'Frozen acquisition queue only; no remediation',
            'cost_limit': manifest['campaign_cost_limit'], 'candidate_count': len(manifest['candidates'])},
            cid, cid + '-acquisition-authorization')
        store.append('acquisition_attempt', {'candidate': candidate, 'order': index,
            'authorization_reference': manifest['authorization_reference']}, cid, identity + '-attempt')
        try:
            store.assign_domain(manifest['study_id'], urlsplit(candidate['url']).hostname.lower().removeprefix('www.'), manifest['partition'])
            capture = _existing(store, identity + '-capture') or environment.capture_verified(candidate['url'], cid, identity + '-capture', manifest['evaluator'])
            store.assign_domain(manifest['study_id'], urlsplit(capture['data']['captured_url']).hostname.lower().removeprefix('www.'), manifest['partition'])
            rendered_hash = store.get(capture['data']['rendered_id'])['data']['sha256']
            store.assign_domain(manifest['study_id'], 'snapshot:' + rendered_hash, manifest['partition'])
            admission = _capture_admission(store, capture, cid)
            if admission['data']['status'] != 'passed':
                raise ContractError('Captured page rejected: ' + str(admission['data']['reasons']))
            _native_reference(capture)
            capture, source, audit, replay = _reference(store, environment, capture, cid, identity, manifest['evaluator'])
            capture, source, audit, replay, repeat = _repeat(store, environment, capture, source, audit, replay, cid, identity, manifest['evaluator'])
            from .capture_admission import assess
            if assess(source, capture['data'])['status'] != 'passed':
                raise ContractError('Prepared input is not a meaningful admitted page')
            from .evidence_verifier import verify, BASELINE_VERSION
            visual_id = identity + '-visual-' + digest({'capture': capture['id'],
                'audit': audit['id'], 'repeat': repeat['id'], 'review_contract': BASELINE_VERSION})[:16]
            visual = verify(store, providers, identity, visual_id, capture, audit, replay, manifest['capture_verifier'])
            if visual['data']['status'] != 'admitted':
                from .source_recovery import recover
                alternative = recover(store, environment, capture, source, audit, replay, cid, visual_id, manifest['evaluator'], verification=visual)
                if alternative[0]['id'] != capture['id']:
                    capture, source, audit, replay, repeat = _repeat(store, environment, *alternative, cid, visual_id + '-recovered', manifest['evaluator'])
                    _native_reference(capture)
                    if assess(source, capture['data'])['status'] != 'passed':
                        raise ContractError('Recovered input is not a meaningful admitted page')
                    visual = verify(store, providers, identity, visual_id + '-recovered', capture, audit, replay, manifest['capture_verifier'])
            if visual['data']['status'] != 'admitted':
                raise ContractError('Visual reproduction requires review: ' + str(visual['data'].get('rationale')))
            admission = _capture_admission(store, capture, cid)
            from .category_review import review
            rendered_id = capture['data']['rendered_id']
            rendered = store.read_blob(rendered_id).decode()
            category_id = identity + '-category-' + digest({'rendered_id': rendered_id, 'model': manifest['category_review_model']})[:16]
            category = None
            category_error = None
            try:
                category = review(store, providers, identity, category_id, manifest['category_review_model'],
                    {'id': candidate['candidate_id'], 'source_result_id': rendered_id, 'url': candidate['url'],
                     'captured_url': capture['data']['captured_url'], 'page_title': capture['data'].get('visible', {}).get('title')}, rendered)
            except (BudgetStop, UncertainCall):
                raise
            except ContractError as error:
                category_error = str(error)
                store.append('category_review_failure', {'capture_id': capture['id'],
                    'rendered_id': rendered_id, 'category_id': category_id, 'error': category_error,
                    'automatic_retry': False}, cid, category_id + '-failure')
            from .controller import profile
            page = store.append('page', {'source': candidate, 'capture_id': capture['id'], 'original_id': capture['data']['replay_source_id'],
                'audit_id': audit['id'], 'capture_admission_id': admission['id'], 'replay_admission_id': replay['id'],
                'repeatability_id': repeat['id'], 'verification_id': visual['id'],
                'category_review_id': category['id'] if category else None, 'category_error': category_error,
                'profile': profile(source, audit['data'], capture['data']['captured_url']) |
                    {'category': category['data']['category'] if category else 'unknown',
                     'category_source': category['id'] if category else category_id + '-failure'},
                'partition': manifest['partition'], 'human_verified': False}, cid, identity + '-page')
            outcome = {'status': 'automatically_admitted_pending_human', 'page_id': page['id']}
        except (BudgetStop, UncertainCall):
            raise
        except requests.RequestException as error:
            store.append('acquisition_failure', {'candidate': candidate, 'attempt_id': identity + '-attempt',
                'error': str(error), 'artifacts_retained': True}, cid, identity + '-failure')
            outcome = {'status': 'unavailable', 'page_id': None, 'reason': str(error)}
        except (ContractError, ValueError, OSError, KeyError) as error:
            store.append('acquisition_failure', {'candidate': candidate, 'attempt_id': identity + '-attempt',
                'error': str(error), 'artifacts_retained': True}, cid, identity + '-failure')
            outcome = {'status': 'rejected', 'page_id': None, 'reason': str(error)}
        return store.append('acquisition_result', {'candidate_id': candidate['candidate_id'], 'order': index,
            'attempt_id': identity + '-attempt', 'human_verified': False, **outcome}, cid, identity + '-outcome')
