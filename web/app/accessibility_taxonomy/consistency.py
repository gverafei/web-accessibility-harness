"""Diagnose verdict flips without relabeling measurements or calling a judge."""
from harness.contracts import digest

VERSION = 'same-evidence-verdict-review-v2'
STOP_REASON = 'Contextual evaluator changed its verdict on an unchanged target; measurement review is required before further generation'
CONTEXTUAL_METHODS = frozenset({'decisions', 'luna_contextual'})


def compare(before, after):
    """Distinguish reassessment after a context edit from conflicting equal evidence.

    Target markup alone is not the evidence of a relational criterion. Keep the
    new verdict and diagnostic history when its supplied context changes; only
    equal-context conflicts or unexpected instrument changes block execution.
    """
    prior = {(row['type'], row['opportunity_id']): row
             for row in before['opportunities'] if row.get('method') in CONTEXTUAL_METHODS}
    changes = []
    for row in after['opportunities']:
        old = prior.get((row['type'], row['opportunity_id']))
        if (not old or row.get('method') not in CONTEXTUAL_METHODS
                or {old.get('status'), row.get('status')} != {'passed', 'failed'}):
            continue
        old_context, new_context = old.get('context', {}), row.get('context', {})
        element = old_context.get('element')
        if not element or element != new_context.get('element'):
            continue
        fields = sorted(key for key in old_context.keys() | new_context.keys()
                        if old_context.get(key) != new_context.get(key))
        instrument_changed = any(before.get(key) != after.get(key)
                                 for key in ('model', 'judge_protocol', 'version', 'catalog_version'))
        scope_changed = before.get('scope') != after.get('scope')
        classification = ('judge_model_changed' if instrument_changed
                          else 'context_changed_reassessment' if fields or scope_changed
                          else 'identical_context_verdict_conflict')
        changes.append(dict(type=row['type'], identity=row.get('identity_basis'),
            before_opportunity_id=old['opportunity_id'], after_opportunity_id=row['opportunity_id'],
            before_status=old['status'], after_status=row['status'],
            target_sha256=digest(element), before_context_sha256=digest(old_context),
            after_context_sha256=digest(new_context), changed_context_fields=fields,
            changed_assessment_fields=['scope'] if scope_changed else [],
            classification=classification,
            review_required=classification != 'context_changed_reassessment'))
    return dict(version=VERSION, review_required=any(row['review_required'] for row in changes), changes=changes,
        raw_measurements_modified=False,
        scope='Equal-target context edits retain their current verdict without proving inconsistency; equal-evidence conflicts and instrument changes require review')


def record(store, campaign, before_id, measurement):
    after_id = (measurement or {}).get('retained_assessment_id')
    if not before_id or not after_id or before_id == after_id:
        return None
    before, after = store.get(before_id), store.get(after_id)
    review = compare(before['data'], after['data'])
    if not review['changes']:
        return None
    data = dict(review, before_assessment_id=before_id, before_assessment_hash=before['hash'],
                after_assessment_id=after_id, after_assessment_hash=after['hash'])
    return store.append('taxonomy_consistency_review', data, campaign,
                        'taxonomy-consistency-'+digest(data))


def pending(state):
    return bool((state.get('evaluator_consistency_review') or {}).get('review_required'))


def attach(state, review):
    """A new context diagnostic cannot clear a previously unresolved conflict."""
    if review and not (pending(state) and not review['data']['review_required']):
        state['evaluator_consistency_review'] = dict(review['data'], record_id=review['id'])
