"""Restore deterministic loop context before replaying a paid pending request."""
import json
import hashlib

from .contracts import ContractError, digest

VERSION = 'fixed-policy-loop-checkpoint-v1'


def active_route(context, completed, workers):
    """Restore the committed route before testing whether the next route changed."""
    level, worker_id = context.get('active_wire_level'), context.get('active_worker_id')
    if level is None or worker_id is None:
        if not completed or completed[-1]['iteration_number'] != context['completed_iteration']:
            raise ContractError('Legacy route recovery requires its last committed iteration')
        strategy = json.loads(completed[-1]['strategy_json'])
        level, worker_id = strategy['wire_level'], strategy['harness']['worker_id']
    worker = next((row for row in workers if row['id'] == worker_id), None)
    if type(level) is not int or not 1 <= level <= 5 or worker is None:
        raise ContractError('Checkpoint route is outside the frozen worker pool')
    return level, worker


def validate_iteration_boundary(completed, state, store):
    """Raw attempt slots include paid proposals that did not create a page."""
    measured = [row['iteration_number'] for row in completed]
    skipped = [store.get(ident)['data']['iteration']
               for ident in state.get('unmeasured_proposals', [])]
    slots = measured + skipped
    return (len(slots) == len(set(slots))
            and sorted(slots) == list(range(1, state['iteration'] + 1)))


def validate_audit_source(audit, source, required=False):
    expected = audit['data'].get('replay', {}).get('input_document_sha256')
    if required and not expected:
        raise ContractError('Cached candidate audit lacks its input document identity')
    if expected and hashlib.sha256(source.encode()).hexdigest() != expected:
        raise ContractError('Cached audit and candidate bytes differ; do not reuse the measurement')


def progress_context(context, completed):
    """Recover missing counters from committed candidate selections, not guesses."""
    if 'progress_state' in context or not completed:
        return context
    strategies = [json.loads(row['strategy_json']) for row in completed]
    selections = [strategy.get('candidate_selection', {}) for strategy in strategies]
    if not all('best_so_far' in selection and 'gate_distance' in selection for selection in selections):
        return context
    stagnant = marginal = 0
    basis = 'initial_source'
    for selection in selections:
        if selection['best_so_far']:
            stagnant = 0
            basis = selection.get('improvement_basis', basis)
            marginal = marginal + 1 if selection.get('marginal_progress') else 0
        else:
            stagnant += 1
    latest = selections[-1]
    return dict(context, progress_state={
        'stagnant_attempts': stagnant, 'marginal_attempts': marginal,
        'last_improvement_basis': basis,
        'previous_progress': {'quality':latest['gate_distance'],
                              'retention':strategies[-1].get('content_retention', {})}})


def restore(store, state, campaign, run_id, completed):
    context = state.get('loop_context')
    if context:
        if (context.get('version') != VERSION
                or context['completed_iteration'] != state['iteration']
                or context['incumbent_source_id'] != state['incumbent']['source_id']):
            raise ContractError('Loop checkpoint differs from the recorded run boundary')
        return progress_context(context, completed)
    # Older runs lack a post-rollback checkpoint. A paid pending patch request
    # contains the exact feedback and plan used at that boundary; never guess it.
    from .providers import Ledger
    key = run_id + '-attempt-' + str(state['iteration']) + ':call:0'
    call = next((row for row in Ledger(store).rows(campaign, run_id)
                 if row['logical_key'] == key and row['status'] == 'received'), None)
    if call is None:
        raise ContractError('Legacy resumption requires the exact paid pending request')
    request = store.get(call['request_id'])['data']['request']
    if digest(request) != call['request_hash']:
        raise ContractError('Paid resumption request checksum differs')
    content = request['messages'][0]['content']
    prompt = content if isinstance(content, str) else content[0]['text']
    try:
        evidence = json.JSONDecoder().raw_decode(prompt.split('Current evidence:\n', 1)[1])[0]
        plan = json.JSONDecoder().raw_decode(prompt.split('\nArchitecture plan: ', 1)[1])[0]
    except (IndexError, ValueError, TypeError) as error:
        raise ContractError('Pending request lacks an exact patch feedback/plan boundary') from error
    if evidence['iteration'] != state['iteration'] + 1:
        raise ContractError('Pending request does not match the next recorded iteration')
    feedback = evidence['previous_evaluation_feedback']
    marker = '\nPending feedback for the retained best page:\n'
    best_feedback = feedback.split(marker, 1)[1] if marker in feedback else feedback
    selected = next(row for row in completed
                    if json.loads(row['strategy_json'])['harness']['retained']
                    and json.loads(row['strategy_json'])['harness']['verification_id']
                    == store.get(state['incumbent']['case_id'])['data']['verification_id'])
    strategy = json.loads(selected['strategy_json'])
    return {'version': VERSION, 'completed_iteration': state['iteration'],
            'incumbent_source_id': state['incumbent']['source_id'],
            'component_plan': plan, 'feedback': feedback, 'best_feedback': best_feedback,
            'best_retention': strategy['content_retention'],
            'best_visual': strategy['candidate_selection'].get('visual_similarity_percent', 100),
            'legacy_paid_request_id': call['request_id']}
