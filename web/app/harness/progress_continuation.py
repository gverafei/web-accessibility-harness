"""Continuation of a fixed intervention, distinct from adaptive P5 selection."""
from .contracts import ContractError,canonical

VERSION='budget-progress-continuation-v4'


def completed_objective(findings, targets, *, allow_minor_visual=False):
    """Stop only on measured targets and complete, clean local review evidence."""
    candidate = findings.get('candidate') or {}
    axe, lighthouse = candidate.get('axe'), candidate.get('lighthouse')
    if (axe is None or lighthouse is None or not targets
            or axe > targets['max_axe'] or lighthouse < targets['min_lighthouse']):
        return False
    minor_only = allow_minor_visual and findings.get('visual_impact') == 'minor'
    informational = {'destination_provenance_requires_human_confirmation'}
    if minor_only:
        informational.add('minor_visual_finding')
    actionable_warnings = [warning for warning in findings.get('visual_warnings', [])
                           if warning not in informational]
    return (findings.get('functional_status') == 'admitted'
            and findings.get('visual_status') == 'admitted'
            and (findings.get('visual_impact') == 'none' or minor_only)
            and not findings.get('functional_reasons')
            and not actionable_warnings
            and not findings.get('remaining_lighthouse_failures')
            and not any((findings.get('remaining_taxonomy_failures') or {}).values())
            and not findings.get('destination_repairs'))


def relation(previous,current):
    """Pareto direction of the two audits; trade-offs remain explicit."""
    better=current['axe']<previous['axe'] or current['lighthouse']>previous['lighthouse']
    worse=current['axe']>previous['axe'] or current['lighthouse']<previous['lighthouse']
    return 'tradeoff' if better and worse else 'improved' if better else 'worse' if worse else 'tie'


def append(history,original,current):
    previous=history[-1] if history else original
    direction=relation(previous,current)
    streak=(history[-1].get('consecutive_regressions',0) if history else 0)+1 if direction=='worse' else 0
    return [*history,{**current,'direction':direction,'consecutive_regressions':streak}]


def supported_progress(history, limits, findings):
    """Allow another bounded repair after two preserving, measured gains."""
    if len(history) < 2:
        return False
    attempt_limit = limits.get('attempt_limit')
    iteration = limits.get('iteration')
    run_limit = limits.get('run_limit_usd')
    spent = limits.get('spent_usd')
    if (attempt_limit is None or iteration is None or iteration >= attempt_limit
            or run_limit is None or spent is None or spent >= run_limit):
        return False
    if (findings.get('functional_status') != 'admitted'
            or findings.get('visual_status') != 'admitted'
            or findings.get('visual_impact') != 'none'
            or findings.get('functional_reasons')):
        return False
    for measured in history[-2:]:
        retention = measured.get('content_retention') or {}
        if (measured.get('direction') != 'improved'
                or measured.get('retained') is not True
                or any(retention.get(key) != 100 for key in
                       ('text_percent', 'links_percent', 'images_percent'))):
            return False
    candidate = findings.get('candidate') or {}
    if any(candidate.get(key) != history[-1].get(key)
           for key in ('axe', 'lighthouse')):
        return False
    # Counts alone do not identify a supported next repair. Require a measured
    # browser finding with a concrete target; the intervention still validates
    # every proposed operation and dependency before applying it.
    return any(item.get('selector') for failure in
               findings.get('remaining_lighthouse_failures', [])
               for item in failure.get('items', []))


def choose(store,providers,run,ident,model,history,limits,findings):
    try:return store.get(ident)
    except KeyError:pass
    # A first candidate needs a correction opportunity only while work remains.
    candidate = findings.get('candidate') or {}
    if (limits.get('stop_at_perfect_audit') is True
            and candidate.get('axe') == 0 and candidate.get('lighthouse') == 100):
        action, reason = 'stop', 'perfect_audit_stop_requested'
    elif completed_objective(findings, limits.get('targets')):
        action, reason = 'stop', 'targets_met_without_remaining_findings'
    elif len(history) < 2:
        action, reason = 'continue', 'initial_correction_opportunity'
    elif history[-1]['consecutive_regressions'] >= 2:
        action, reason = 'stop', 'two_consecutive_audit_regressions'
    elif supported_progress(history, limits, findings):
        action, reason = 'continue', 'preserving_progress_with_measured_repair_targets'
    else:
        action, reason = None, None
    answers=None
    if action is None:
        answers=providers.decisions(run,'repair',ident+':decision',canonical({'history':history,'reference_limits':limits,'remaining_findings':findings}),
            [{'name':'action','type':'choice','instructions':'Continue the SAME fixed strategy and worker when a concrete useful repair remains. An explicit attempt_limit and recorded USD limits are hard and cannot be extended. The time reference is soft under this policy; measured progress can justify continuing beyond that reference within the hard limits. Stop when no supported useful repair remains; never claim that inaccessible content was fixed merely because it disappeared. An imperfect page is feedback, not a rejected page.',
              'choices':[{'value':'continue','description':'Another targeted correction is worthwhile given measured progress, remaining defects and available money.'},
                         {'value':'stop','description':'No supported useful correction remains within this fixed intervention; deliver the best measured proposal.'}]}],model=model)
        action=answers.get('action',{}).get('choice')
        if action not in ('continue','stop'):raise ContractError('Invalid continuation response; no inferred action')
        reason='recorded_decision'
    scope = ('Fixed strategy and model; evaluated-candidate limit; generation retries bounded by time and USD reservations.'
             if limits.get('iteration_unit') == 'evaluated candidates' else
             'Fixed strategy and model; soft time/iteration references; unchanged hard USD reservations.')
    return store.append('progress_continuation',{'version':VERSION,'run_id':run,'history':history,'reference_limits':limits,'findings':findings,'action':action,'reason':reason,'answers':answers,
        'scope':scope},providers.campaign,ident)
