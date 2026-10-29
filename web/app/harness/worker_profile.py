"""Current experimental worker boundary, independent of provider adapters."""
from .contracts import ContractError
VERSION = 'controlled-worker-configurations-v8'
CONFIGURATIONS = frozenset({('openai/gpt-6-luna', 'low'),
                           ('openai/gpt-6-luna', 'high'),
                           ('openai/gpt-6-luna', 'medium'),
                           ('openai/gpt-6-luna', 'xhigh'),
                           ('openai/gpt-6.1-sol', 'low'),
                           ('openai/gpt-6.1-sol', 'high'),
                           ('openai/gpt-6-astra', 'low'),
                           ('openai/gpt-6-astra', 'high'),
                           ('anthropic/claude-opus-5.5', 'low'),
                           ('anthropic/claude-opus-5.5', 'high'),
                           ('anthropic/claude-sonnet-5.5', 'low'),
                           ('anthropic/claude-sonnet-5.5', 'high'),
                           ('anthropic/claude-haiku-5.5', 'low'),
                           ('anthropic/claude-haiku-5.5', 'high')})
MESSAGE = 'Choose a permitted model and reasoning configuration.'

def allowed(model):
    return (model.get('provider', 'openrouter') == 'openrouter' and
            (model.get('model'), model.get('reasoning_effort')) in CONFIGURATIONS)

def validate(workers):
    if not workers or any(not allowed(worker) for worker in workers):
        raise ContractError(MESSAGE)
