"""Intervention changes independently from the experimental acceptance contract."""
from decimal import Decimal, InvalidOperation

COMMON_CONDITIONS = {
    "iterations": 3, "lighthouse": 90, "axe": 5, "aim": 9,
    "rag_top_k": 4, "review": "automated",
    "cost": 0.25, "seconds": 360,
}


def common_conditions(settings=None):
    """Resolve study targets once; callers persist them with the new run."""
    conditions = dict(COMMON_CONDITIONS)
    for setting, name, upper in (
        ('remediation_min_lighthouse', 'lighthouse', 100),
        ('remediation_max_axe', 'axe', 2147483647),
    ):
        raw = (settings or {}).get(setting, conditions[name])
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ValueError(f'{setting} must be a whole number.') from None
        if not 0 <= value <= upper:
            raise ValueError(f'{setting} must be between 0 and {upper}.')
        conditions[name] = value
    settings = settings or {}
    for setting, name, lower, upper in (
        ('remediation_max_iterations', 'iterations', 1, 10),
        ('remediation_max_execution_seconds', 'seconds', 30, 7200),
    ):
        raw = str(settings.get(setting, conditions[name])).strip()
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError(f'{setting} must be a whole number.') from None
        if not lower <= value <= upper:
            raise ValueError(f'{setting} must be between {lower} and {upper}.')
        conditions[name] = value
    raw = str(settings.get('remediation_max_cost_usd', conditions['cost'])).strip()
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise ValueError('Invalid remediation cost limit.') from None
    if not amount.is_finite() or not Decimal('.01') <= amount <= Decimal('100'):
        raise ValueError('Remediation cost limit must be between 0.01 and 100 USD.')
    conditions['cost'] = float(amount)
    return conditions


def automatic_recipe(priority, execution_mode="iterative", settings=None):
    conditions = common_conditions(settings)
    if execution_mode == "single_shot":
        return {**conditions, "iterations":1, "temperature":0.20,
                "tier":"low"}
    intervention = {
        15: (0.05, "low"),
        35: (0.20, "low"),
        55: (0.50, "medium"),
        75: (0.50, "high"),
        90: (0.50, "xhigh"),
    }[priority]
    recipe = {**conditions, **dict(zip(
        ("temperature", "tier"), intervention))}
    if execution_mode == 'regenerate_only':
        recipe['iterations'] = 1
    return recipe
