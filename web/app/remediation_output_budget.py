"""Shared completion allowance includes reasoning as well as visible output."""
import os

VERSION = 'reasoning-inclusive-output-budget-v3'
MAX_OUTPUT_TOKENS = 32000
FULL_DOCUMENT_OUTPUT_TOKENS = 128000


def output_token_ceiling(settings, model, explicit_limit=None):
    configuration = settings.get('_model_configuration') or {}
    maximum = configuration.get('max_completion_tokens')
    matched = configuration.get('model') == model
    if (matched and configuration.get('reasoning_effort') in {'high', 'xhigh', 'max'}
            and type(maximum) is int and maximum > 0):
        return maximum
    ceiling = int(os.getenv('REMEDIATION_OUTPUT_TOKEN_LIMIT', str(explicit_limit or MAX_OUTPUT_TOKENS)))
    if explicit_limit is not None:
        ceiling = min(ceiling, explicit_limit)
    if matched and isinstance(maximum, int) and maximum > 0:
        ceiling = min(ceiling, maximum)
    return ceiling
