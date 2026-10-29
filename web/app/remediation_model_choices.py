import hashlib
import json
import re
from datetime import datetime, timezone
import requests
PROVIDER_DEFAULT_MODELS = {'openai': 'openai/gpt-6-luna', 'google': 'google/gemini-3.8-flash', 'meta-llama': 'meta-llama/llama-4-maverick', 'qwen': 'qwen/qwen3-coder-plus', 'anthropic': 'anthropic/claude-opus-5.5'}
"""Researcher-managed choices; each run freezes its model configuration."""
import json
import re
from pathlib import Path
from model_catalog_metadata import compatible, discover, reviewed_metadata

def bundled_metadata():
    return json.loads(Path(__file__).with_name('model_metadata.json').read_text())

CATALOG_SETTING = 'remediation_model_catalog_json'
TIERS = ('low', 'medium', 'high', 'xhigh', 'max')
EFFORTS = (None, 'none', 'minimal', 'low', 'medium', 'high', 'xhigh')


def default_catalog():
    definitions = (
        ('openai/gpt-6-luna', 'GPT-6 Luna', 'low', 'low', '#2f9e66', True, False),
        ('openai/gpt-6-luna', 'GPT-6 Luna', 'high', 'high', '#9b4fc2', True, False),
        ('openai/gpt-6.1-sol', 'GPT-6.1 Sol', 'xhigh', 'low', '#c3486b', True, False),
    )
    return [dict(bundled_metadata().get(model,{}),id=model + ('@high' if model in ('openai/gpt-6-luna','anthropic/claude-haiku-5.5') and effort == 'high' else ''),
                 model=model, label=label, tier=tier, reasoning_effort=effort, color=color,
                 vision=bundled_metadata().get(model,{}).get('vision',vision), temperature_supported=bundled_metadata().get(model,{}).get('temperature_supported',temperature), reasoning_supported=effort is not None,
                 enabled=True, supported_parameters=bundled_metadata().get(model,{}).get('supported_parameters',['reasoning'] if effort else []),
                 is_default=model == 'openai/gpt-6-luna' and effort == 'low',
                 metadata_source=bundled_metadata().get(model,{}).get('metadata_source','bundled research configuration'))
            for model, label, tier, effort, color, vision, temperature in definitions]


def validate_catalog(catalog, metadata=None):
    metadata = reviewed_metadata() if metadata is None else metadata
    if not isinstance(catalog, list) or not 1 <= len(catalog) <= 32:
        raise ValueError('Keep between 1 and 32 model choices.')
    result, ids = [], set()
    for item in catalog:
        if not isinstance(item, dict):
            raise ValueError('Each model choice must be an object.')
        model, ident = str(item.get('model', '')).strip(), str(item.get('id', '')).strip()
        approved = metadata.get(model, {})
        if 'decisions' in approved.get('output_modalities', []) or model in ('openai/gpt-6-luna-decisions','typesafe/jev-1.13'):
            raise ValueError('Configure decision models in the Decision models tab.')
        if not compatible(approved):
            raise ValueError('Choose a discovered model with text, JSON and output-limit support.')
        if not re.fullmatch(r'[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.:/-]+', model) or model.startswith(('ollama/', 'openrouter/')):
            raise ValueError('Choose an explicit cloud model identifier, not a router or local alias.')
        if not re.fullmatch(r'[a-zA-Z0-9_./:@-]{1,240}', ident) or ident in ids:
            raise ValueError('Every choice needs a unique identifier.')
        ids.add(ident)
        label = str(item.get('label') or model).strip()
        if not 1 <= len(label) <= 120 or item.get('tier') not in TIERS:
            raise ValueError('Provide a short name and valid experimental tier.')
        effort = item.get('reasoning_effort')
        if effort not in EFFORTS or effort is not None and not approved.get('reasoning_supported'):
            raise ValueError('Choose a supported reasoning setting.')
        color = str(item.get('color', ''))
        if not re.fullmatch(r'#[a-fA-F0-9]{6}', color):
            raise ValueError('Choose a valid model color.')
        parameters = item.get('supported_parameters') or []
        if not isinstance(parameters, list) or len(parameters) > 60 or any(not isinstance(p, str) or len(p) > 80 for p in parameters):
            raise ValueError('Invalid capability metadata.')
        result.append({**approved,
                       'id': ident, 'model': model, 'label': label, 'tier': item['tier'],
                       'reasoning_effort': effort, 'color': color, 'enabled': item.get('enabled', True) is True,
                       'is_default': item.get('is_default') is True,
                       'vision': approved.get('vision') is True, 'temperature_supported': approved.get('temperature_supported') is True,
                       'reasoning_supported': approved.get('reasoning_supported') is True, 'supported_parameters': approved.get('supported_parameters', [])})
    if not any(item['enabled'] for item in result):
        raise ValueError('Keep at least one enabled model choice.')
    defaults = [item for item in result if item['is_default']]
    if len(defaults) > 1 or defaults and not defaults[0]['enabled']:
        raise ValueError('Choose only one enabled default model.')
    return result


def configured_catalog(settings=None):
    raw = (settings or {}).get(CATALOG_SETTING)
    catalog = validate_catalog(json.loads(raw), reviewed_metadata(settings)) if raw else default_catalog()
    from harness.worker_profile import allowed
    # Preserve saved identities, colours and order; historical presentation uses
    # frozen snapshots. Availability follows the current experimental profile.
    return [dict(c, enabled=c['enabled'] and allowed(c),
                 is_default=c['is_default'] and c['enabled'] and allowed(c)) for c in catalog]










def discover_models(settings):
    """Only models supporting the text/JSON/bounded-output tasks used here."""
    return discover(settings)


def model_choices(settings=None):
    choices = []
    for item in configured_catalog(settings):
        if not item['enabled']:
            continue
        effort = item['reasoning_effort']
        suffix = ' · ' + ('Light' if effort == 'low' else effort.title()) + ' reasoning' if effort else ''
        choices.append({**item, 'name': item['label'] + suffix})
    return choices

def model_choice(ident, settings=None):
    for choice in model_choices(settings):
        if choice['id'] == ident:
            return choice
    raise ValueError('Choose an enabled model from the configured catalogue.')

def frozen_model_configuration(choice):
    # Saving a catalogue may add optional null metadata fields. Those do not
    # change the selected experimental configuration or its identity.
    snapshot = {**{key: value for key, value in choice.items() if value is not None}, 'schema_version': 1}
    snapshot['digest'] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return snapshot

def run_model_presentation(run):
    """Display the run's frozen choice, not today's mutable catalogue."""
    try:
        frozen = json.loads(run.get('model_config_json') or '{}')
    except (ValueError, TypeError):
        frozen = {}
    if not isinstance(frozen, dict) or frozen.get('model') != run.get('generator_model'):
        frozen = {}
    tier = frozen.get('tier') or run.get('model_cost_tier') or 'low'
    if not isinstance(tier, str) or tier not in (*TIERS, 'local'):
        tier = 'low'
    if str(run.get('generator_model') or '').startswith('ollama/'):
        tier = 'local'
    colors = {'local':'#64748b', 'low':'#2f9e66', 'medium':'#2686c9',
              'high':'#6558c8', 'xhigh':'#9b4fc2', 'max':'#c3486b'}
    color = str(frozen.get('color') or '')
    if not re.fullmatch(r'#[a-fA-F0-9]{6}', color):
        color = colors.get(tier, '#18529d')
    label = frozen.get('label')
    effort = frozen.get('reasoning_effort')
    return {'tier':tier, 'color':color, 'label':label if isinstance(label, str) else None,
            'reasoning_effort':effort if isinstance(effort, str) and effort in EFFORTS else None}
