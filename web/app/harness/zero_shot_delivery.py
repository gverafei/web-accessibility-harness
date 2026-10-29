"""Delivery replacements preserve run identity, evidence lineage and resource totals."""
import json
from decimal import Decimal

from remediation_baseline import baseline_candidate
from .contracts import ContractError, digest
from .providers import Ledger


def active_candidate(store, sql_run_id, iteration):
    """Resolve an explicitly committed replacement instead of a legacy attempt slot."""
    if iteration != 1:
        return None
    rid = 'sql-run-' + str(sql_run_id)
    revisions = [r for r in store.list('zero_shot_delivery_revision')
                 if r['data']['outcome']['run_id'] == rid
                 and store.checkpoint(r['id'] + '-application')[0].get('committed') is True]
    if not revisions:
        return None
    revision = revisions[-1]
    selected = revision['data']['outcome']['selected']
    audit = store.get(selected['audit_id'])
    case = store.get(selected['case_id'])
    verification = store.get(case['data']['verification_id'])
    source = store.get(selected['source_id'])
    if (selected.get('original') is not False or audit['kind'] != 'audit'
            or case['data']['run_id'] != rid
            or verification['data']['audit_id'] != audit['id']
            or audit['data']['replay'].get('input_document_sha256') != source['data']['sha256']):
        raise ContractError('Committed delivery evidence does not identify the selected candidate')
    return {'revision': revision, 'audit': audit, 'verification': verification}


def delivery_request(original_request, prefix):
    """A declared delivery clarification keeps the complete source and parameters."""
    import copy
    request = copy.deepcopy(original_request)
    messages = request.get('messages') or []
    if (len(messages) != 1 or messages[0].get('role') != 'user'
            or not isinstance(messages[0].get('content'), str) or not prefix):
        raise ContractError('Delivery clarification requires the original one-message request')
    messages[0]['content'] = prefix + messages[0]['content']
    return request


def first_page(store, calls, original_request, allowed_prefixes=()):
    """Choose by HTML availability only, never by an audit or preservation score."""
    selected = None
    generators = sorted((c for c in calls if c['account'] == 'repair'),
                        key=lambda c: (c['created'], c['id']))
    allowed = {digest(original_request), *(digest(delivery_request(original_request, prefix))
                                          for prefix in allowed_prefixes)}
    for call in generators:
        if (call['status'] != 'received' or call['cost_status'] not in
                ('provider_reported', 'reconciled', 'local') or not call.get('response_id')):
            raise ContractError('Delivery replacement requires resolved complete responses')
        request = store.get(call['request_id'])['data']['request']
        if digest(request) not in allowed:
            raise ContractError('Delivery retry cannot change the original stateless request')
        if selected is not None:
            raise ContractError('Generation must stop at the first executable HTML response')
        payload = json.loads(store.read_blob(call['response_id']))
        choices = payload.get('choices') or []
        if len(choices) != 1 or not isinstance(choices[0].get('message', {}).get('content'), str):
            raise ContractError('Delivery retry requires exactly one textual model response')
        candidate, evidence = baseline_candidate(choices[0]['message']['content'], '')
        if evidence['evaluable']:
            selected = (call, candidate, evidence)
    return selected


def validate_revision(store, revision, incumbent, calls):
    data = revision['data']
    outcome = data['outcome']
    authorization = store.get(data['authorization_id'])
    policy = authorization['data']
    binding = next((b for b in policy['bindings']
                    if b['run_id'] == incumbent['run_id']
                    and b['campaign_id'] == revision['campaign']), None)
    if (authorization['kind'] != 'zero_shot_delivery_authorization' or not binding
            or not policy.get('authorization_reference')
            or policy.get('first_html_only') is not True
            or policy.get('audit_feedback') is not False
            or data.get('raw_receipts_modified') is not False
            or incumbent.get('comparison_mode') != 'zero-shot'
            or incumbent.get('axe') is not None or incumbent.get('lighthouse') is not None):
        raise ContractError('Replacement requires explicit authorization for a missing P0 page')
    original = next((c for c in calls if c['id'] == binding['response_call_id']), None)
    if original is None:
        raise ContractError('The original P0 generation receipt must remain available')
    request = store.get(original['request_id'])['data']['request']
    campaign = store.get(data['measurement_campaign_id'])
    if policy.get('measurement_campaign_id') != campaign['id']:
        raise ContractError('Measurement campaign is outside the authorized replacement phase')
    measured = Ledger(store).rows(campaign['id'], incumbent['run_id'])
    amendments = store.list('zero_shot_delivery_prompt_amendment', campaign['id'])
    if any(a['data'].get('authorization_id') != authorization['id']
           or a['data'].get('source_changed') is not False
           or a['data'].get('audit_feedback') is not False
           or not a['data'].get('authorization_reference') for a in amendments):
        raise ContractError('Delivery clarification requires source-preserving recorded authority')
    result = first_page(store, measured, request,
                        [a['data']['prefix'] for a in amendments])
    if result is None:
        raise ContractError('A refusal cannot acquire invented page measurements')
    call, candidate, _ = result
    selected = outcome['selected']
    audit = store.get(selected['audit_id'])
    attempt = store.get(data['attempt_id'])
    if (call['id'] != data['response_call_id']
            or selected.get('original') is not False
            or store.read_blob(selected['source_id']) != candidate.encode()
            or audit['kind'] != 'audit' or audit['campaign'] != campaign['id']
            or audit['data']['status'] != 'completed'
            or outcome['axe'] != audit['data']['axe']
            or outcome['lighthouse'] != audit['data']['lighthouse']
            or attempt['data']['source_id'] != selected['source_id']
            or attempt['data']['audit_id'] != selected['audit_id']
            or attempt['data']['run_id'] != incumbent['run_id']
            or outcome['attempts'] != [attempt['id']]):
        raise ContractError('Replacement must retain and measure the first actual HTML output')
    prior = {c['id']: c for c in calls if c['id'] in incumbent['costs']['call_ids']}
    expected = {**prior, **{c['id']: c for c in measured}}
    costs = outcome['costs']
    if (set(prior) != set(incumbent['costs']['call_ids'])
            or set(costs['call_ids']) != set(expected)
            or abs(Decimal(str(costs['cost_usd'])) - sum(
                (Decimal(str(c['cost'] or 0)) for c in expected.values()), Decimal(0))) > Decimal('0.000000001')
            or costs['input_tokens'] != sum(c['input_tokens'] or 0 for c in expected.values())
            or costs['output_tokens'] != sum(c['output_tokens'] or 0 for c in expected.values())):
        raise ContractError('Delivery resources must retain original, retry and measurement charges')
    if any(c['status'] == 'dispatching' or c['cost_status'] not in
           ('provider_reported', 'reconciled', 'local') for c in expected.values()):
        raise ContractError('Unresolved consumption cannot become a completed replacement')


def validate_timing_revision(store, revision, incumbent, calls):
    """Exclude operator pauses while retaining every paid generation and evaluation."""
    data = revision['data']; outcome = data['outcome']
    parent = store.get(data['parent_outcome_id'])
    if parent['kind'] != 'zero_shot_delivery_revision' or parent['data']['outcome'] != incumbent:
        raise ContractError('Delivery timing requires its unchanged measured parent')
    original = store.get(parent['data']['parent_outcome_id'])
    original_outcome = original['data'] if original['kind'] == 'run_result' else original['data']['outcome']
    scoped = Ledger(store).rows(parent['data']['measurement_campaign_id'], incumbent['run_id'])
    generation = [c for c in scoped if c['account'] == 'repair']
    start, end = data['measurement_start'], data['measurement_end']
    source = store.get(incumbent['selected']['source_id'])
    audit = store.get(incumbent['selected']['audit_id'])
    expected = original_outcome['seconds'] + sum(c['elapsed'] or 0 for c in generation) + end - start
    unchanged = dict(outcome, seconds=incumbent['seconds'])
    unchanged.pop('resource_time_basis', None)
    if (unchanged != incumbent or data.get('raw_receipts_modified') is not False
            or data['candidate_sha256'] != source['data']['sha256']
            or end != parent['created'] or not generation
            or start < max(c['created'] + (c['elapsed'] or 0) for c in generation)
            or not start <= audit['created'] <= end
            or abs(outcome['seconds'] - expected) > .001
            or not 0 < outcome['seconds'] <= incumbent['seconds'] + .001):
        raise ContractError('Timing must retain requests and the observed evaluation interval only')
