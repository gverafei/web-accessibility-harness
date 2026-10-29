"""Keep research target attainment separate from result availability."""


def measurable_noop(patch_result):
    """Recognize a valid empty patch, separately from rejected operations."""
    return (isinstance(patch_result, dict) and patch_result.get('applied') == []
            and patch_result.get('skipped') == [])


def unchanged_proposal(parent, candidate, patch_result, mutations=()):
    """Skip another audit of the measured parent, never of a changed page.

    Parsing an empty patch can reserialize HTML. With no applied operations or
    deterministic mutations, preserve the exact parent instead of that artifact.
    Invalid/rejected operations retain their separate output-contract handling.
    """
    if not isinstance(patch_result, dict) or patch_result.get('skipped'):
        return False
    return parent == candidate or (measurable_noop(patch_result) and not mutations)


NOOP_FEEDBACK = (
    'The last proposal made no effective edit. The existing measured document '
    'and findings remain current; no new audit or candidate was created. '
    'Inspect the affected control and its existing attributes before concluding '
    'that no bounded repair is possible. Respect every intervention permission; '
    'do not use class changes to bypass forbidden CSS or conceal a defect.'
)


REPEATED_PROPOSAL_FEEDBACK = (
    'This proposal reproduces HTML already measured in this run. Its earlier '
    'measurements are retained; no new audit or evaluated candidate was created. '
    'The current best page is unchanged. Choose a different bounded repair '
    'grounded in its pending findings instead of repeating the same output.'
)


def achieved_feedback(axe_findings, lighthouse_findings):
    rules=', '.join(str(item.get('rule') or item.get('id') or 'unclassified') for item in axe_findings) or 'none reported'
    return ('Automated targets achieved; this does not certify absence of accessibility barriers. '
            f'Remaining Axe rules: {rules}. Lighthouse audit findings: {len(lighthouse_findings)}.')


def completion_status(accepted, evaluated_count, review_policy, targets_achieved):
    if accepted:
        return 'accepted'
    if not evaluated_count:
        return 'failed'
    if review_policy == 'automated':
        return 'completed_with_warnings'
    return 'review_not_achieved' if targets_achieved else 'metrics_not_achieved'


def retain_interrupted_result(best_evaluated_iteration, review_policy, provider_failure):
    """Only retain committed measured results; never bypass specialist review."""
    return bool(best_evaluated_iteration and review_policy == 'automated' and provider_failure)


DYNAMIC_CONTINUATION_VERSION = 'dynamic-continuation-v3'

def refinement_potential(previous, quality, retention, syntax_passed=True):
    """Measured progress permits another attempt, never candidate promotion."""
    if not previous or not syntax_passed:
        return []
    reasons = []
    if quality < previous['quality']:
        reasons.append('accessibility_progress')
    for key in ('text_percent', 'links_percent', 'images_percent', 'dynamic_images_percent'):
        before = previous['retention'].get(key)
        after = retention.get(key)
        if before is not None and after is not None and after > before:
            reasons.append(key + '_progress')
    return reasons


def localized_syntax_recovery(previous, quality, assessment, already_used=False):
    """One corrective opportunity for measured progress, without retaining invalid HTML."""
    if already_used or not previous or quality >= previous['quality']:
        return False
    checks = assessment.get('checks', {})
    errors = checks.get('syntax_nonregression', {}).get('introduced', [])
    return (checks.get('audit') == 'completed'
            and checks.get('observable_preservation', {}).get('status') == 'passed'
            and (checks.get('capture_verification') or {}).get('status') == 'admitted'
            and 0 < len(errors) <= 3
            and all(e.get('selector') and e.get('rule') in
                    ('element-permitted-parent', 'element-permitted-content') for e in errors))


def initial_progress(quality):
    """The audited source is the first comparable accessibility observation."""
    return {'quality':quality,'retention':{}}
