"""Reasoning defaults for explicit agent calls, not automatic model pools."""
from remediation_model_choices import default_catalog

EFFORT_LABELS = {None: 'No adjustable reasoning', 'none': 'Disabled reasoning',
                'minimal': 'Minimal reasoning', 'low': 'Light reasoning',
                'medium': 'Medium reasoning', 'high': 'High reasoning', 'xhigh': 'Extra-high reasoning'}


def reasoning_effort(model, tier):
    choices = [choice for choice in default_catalog() if choice['model'] == model]
    choice = next((choice for choice in choices if choice['tier'] == tier), choices[0] if choices else None)
    return choice['reasoning_effort'] if choice else None


def reasoning_label(model, tier):
    return EFFORT_LABELS[reasoning_effort(model, tier)]
