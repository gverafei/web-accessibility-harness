"""Explicit classifier choices and secret-free configuration snapshots."""
import hashlib
import json
import uuid

from local_llm import local_configuration
from remediation_model_choices import configured_catalog
from harness.decision_models import catalogue as decision_catalogue, snapshot as decision_snapshot


def category_model_options(settings):
    choices, local_error = [], False
    try:
        config = local_configuration(settings)
        if config:
            identifier = 'ollama/' + config['model']
            choices.append({'id': identifier, 'model': identifier,
                'label': config['model'], 'provider': 'local', 'enabled': True,
                'is_default': False, 'config': config})
    except (ValueError, TypeError):
        local_error = True
    default = next((item for item in configured_catalog(settings)
                    if item['enabled'] and item['is_default']), None)
    if default:
        choices.append({'id': default['id'], 'model': default['model'],
            'label': default['label'], 'provider': 'cloud', 'is_default': True,
            'enabled': bool(settings.get('openrouter_api_key')),
            'config': {'model': default['model'],
                'base_url': settings.get('openrouter_base_url') or 'https://openrouter.ai/api/v1',
                'reasoning_effort': default['reasoning_effort'],
                'supported_parameters': default['supported_parameters']}})
    for item in decision_catalogue(settings):
        if item['enabled']:
            choices.append({'id': item['id'], 'model': item['model'],
                'label': item['label'] + ' · Decisions API', 'provider': 'decisions',
                'is_default': False, 'enabled': bool(settings.get('openrouter_api_key')),
                'config': {'definition': decision_snapshot(item),
                    'base_url': settings.get('openrouter_base_url') or 'https://openrouter.ai/api/v1'}})
    return choices, local_error


def freeze_category_model(choice):
    snapshot = {'schema_version': 1, 'choice_id': choice['id'],
                'model': choice['model'], 'provider': choice['provider'],
                'config': choice['config']}
    if choice['provider'] == 'decisions':
        snapshot['config'] = {**snapshot['config'], 'job_id': uuid.uuid4().hex,
                              'max_call_cost_usd': .25}
    snapshot['digest'] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return snapshot


def resolve_category_model(requested, settings):
    choices, _ = category_model_options(settings)
    if requested == 'local':
        requested = 'ollama/' + str(settings.get('ollama_model') or '')
    elif requested == 'luna':
        # A legacy alias must never silently become a different cloud model.
        requested = 'openai/gpt-6-luna'
    choice = next((item for item in choices if item['id'] == requested and item['enabled']), None)
    if not choice:
        raise ValueError('Select an available category model.')
    return freeze_category_model(choice)


def load_category_snapshot(raw, model):
    if not raw:
        return None  # Jobs created before snapshots keep their stored model ID.
    snapshot = json.loads(raw) if isinstance(raw, str) else dict(raw)
    payload = {key: value for key, value in snapshot.items() if key != 'digest'}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    if (snapshot.get('schema_version') != 1 or snapshot.get('model') != model
            or snapshot.get('provider') not in {'local', 'cloud', 'decisions'}
            or snapshot.get('digest') != digest or not isinstance(snapshot.get('config'), dict)):
        raise ValueError('Invalid saved category model configuration.')
    return snapshot
