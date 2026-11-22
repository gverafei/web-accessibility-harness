"""Explain recorded resource stops without changing execution or accounting."""
from decimal import Decimal, InvalidOperation


def money(value, places):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    if amount and amount < Decimal('0.01'):
        places = max(places, 6)
    return f'{amount:.{places}f}'


def stop_notice(run, translate, manifest=None):
    outcome = run.get('harness_outcome') or {}
    reason = str(run.get('error_message') or outcome.get('stop_reason') or '')
    lowered = reason.lower()
    if 'per-call cost limit' in lowered:
        limits = {(manifest or {}).get(role, {}).get('max_call_cost_usd')
                  for role in ('repair_budget', 'review_budget')}
        limit = money(next(iter(limits)), 2) if len(limits) == 1 else None
        if limit is not None:
            message = translate(
                "The next request's maximum reserved cost exceeded the configured US$%(limit)s per-request limit, so it was not sent.",
                limit=limit)
        else:
            message = translate(
                "The next request's maximum reserved cost exceeded its configured per-request limit, so it was not sent.")
    elif 'bounded request' in lowered or 'cost limit reached' in lowered:
        message = translate('The remaining authorized budget could not cover the maximum reserved cost of another request, so it was not sent.')
    elif 'declared model context bound' in lowered:
        message = translate('The complete request exceeded the model context limit. It was not truncated.')
    elif 'provider call limit' in lowered:
        message = translate('The configured model request count limit stopped further work.')
    elif 'time limit' in lowered:
        message = translate('The configured execution time limit stopped further work.')
    elif (run.get('progress_message') or '').startswith('Resource limit reached'):
        message = reason or translate('A configured resource limit stopped further work.')
    else:
        return None
    spent = money(run.get('total_cost_usd'), 6)
    budget = money(run.get('max_cost_usd'), 2)
    if spent is not None and budget is not None:
        message += ' ' + translate('Recorded spending: US$%(spent)s of US$%(budget)s.', spent=spent, budget=budget)
    message += ' ' + translate('Evaluated results are preserved below.')
    return {'message': message}
