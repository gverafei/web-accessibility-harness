"""Brief continuation explanations from recorded evidence, without new inference."""

def continuation_note(item, run, has_next, translate):
    review = item.get('continuation_review') or {}
    closed = run.get('status') not in ('queued', 'running') and not has_next
    continuing = has_next or not closed and review.get('action') == 'continue'
    findings = review.get('findings') or {}
    checks = (item.get('strategy', {}).get('harness', {}).get('assessment') or {}).get('checks', {})
    details = []
    if continuing:
        candidate = findings.get('candidate') or {}
        axe = candidate.get('axe', item.get('axe_violations'))
        if axe:
            details.append(translate('Axe findings: %(count)s', count=axe))
        functional = findings.get('functional_evidence') or {}
        broken = len(functional.get('broken_image_urls') or [])
        if not functional:
            broken = (checks.get('candidate_usability', {}).get('metrics') or {}).get('broken_images', 0)
        if broken:
            details.append(translate('Images not loading: %(count)s', count=broken))
        local_targets = len(functional.get('unresolved_local_targets') or [])
        if local_targets:
            details.append(translate('Unresolved local controls: %(count)s', count=local_targets))
        taxonomy = findings.get('remaining_taxonomy_failures') or {}
        if not taxonomy:
            measured = item.get('strategy', {}).get('harness', {}).get('candidate_taxonomy') or {}
            taxonomy = {key: value.get('failed', 0) for key, value in measured.get('retained', {}).get('categories', {}).items()}
        for category, count in taxonomy.items():
            if count:
                details.append(translate('%(category)s findings: %(count)s', category=translate(category), count=count))
        if findings.get('remaining_lighthouse_failures'):
            details.append(translate('Unresolved Lighthouse checks: %(count)s', count=len(findings['remaining_lighthouse_failures'])))
        visual = findings.get('visual_impact') or checks.get('capture_verification', {}).get('impact')
        if visual == 'material':
            details.append(translate('Visual degradation recorded'))
        if findings.get('destination_repairs'):
            details.append(translate('Link destinations need correction'))
        reason = (translate('The coordinator requested a correction for these recorded findings.') if details
                  else translate('No detailed continuation reason was recorded.'))
        return {'label': translate('Next iteration'), 'reason': reason, 'findings': details}
    if not closed and not review:
        return {'label': translate('Continuation'), 'reason': translate('The continuation decision is pending.'), 'findings': []}
    outcome = run.get('harness_outcome') or {}
    stop = outcome.get('stop_reason') or review.get('reason') or ''
    if run.get('execution_mode') == 'single_shot':
        reason = translate('One generation was configured; no refinement follows.')
    elif stop == 'perfect_audit_stop_requested':
        reason = translate('Axe 0 and Lighthouse 100 reached the configured stopping rule.')
    elif stop == 'targets_met_without_remaining_findings':
        reason = translate('Targets reached with no remaining functional or visual findings.')
    elif 'no effective change' in stop or 'identical HTML' in stop or 'plateau' in stop.lower():
        reason = translate('Further proposals did not produce a useful measured change.')
    elif 'per-call cost limit' in stop.lower():
        reason = translate('The next request exceeded its configured per-request reservation limit; it was not sent.')
    elif 'budget' in stop.lower() or 'cost limit' in stop.lower() or 'reservation' in stop.lower():
        reason = translate('The remaining monetary limit prevents another request.')
    elif 'attempt limit' in stop.lower() or 'iteration limit' in stop.lower():
        reason = translate('The configured iteration limit was reached.')
    elif review.get('reason') == 'two_consecutive_audit_regressions':
        reason = translate('Two consecutive iterations worsened the accessibility measurements.')
    else:
        reason = translate('The coordinator closed the run and retained its measured result.')
    return {'label': translate('Run stopped'), 'reason': reason, 'findings': []}
