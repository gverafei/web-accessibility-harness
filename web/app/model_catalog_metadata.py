"""Provider-advertised admission metadata; discovery never invokes inference."""
import json
import math
import re
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
import requests

def cache_key(kind):
    return kind + '_model_metadata_json'

@lru_cache(maxsize=1)
def vision_metadata():
    return json.loads(Path(__file__).with_name('vision_pricing_metadata.json').read_text())

def reviewed_metadata(settings=None, kind='generative'):
    filename = 'decision_model_metadata.json' if kind == 'decisions' else 'model_metadata.json'
    result = json.loads(Path(__file__).with_name(filename).read_text())
    raw = (settings or {}).get(cache_key(kind))
    if raw:
        result.update(json.loads(raw))
    for model,value in result.items():
        value.update(vision_metadata().get(model,{}))
    return result

def explicit_model(model):
    return isinstance(model, str) and bool(re.fullmatch(r'[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.:/-]+', model)) and not model.startswith(('openrouter/', 'ollama/'))

def compatible(value, kind='generative'):
    try:
        if not explicit_model(value.get('model')): return False
        if 'text' not in value.get('input_modalities', []): return False
        outputs = value.get('output_modalities', [])
        if kind == 'decisions':
            if 'decisions' not in outputs or 'text' in outputs: return False
            if not explicit_model(value.get('response_model')): return False
        else:
            parameters = value.get('supported_parameters', [])
            if 'text' not in outputs or 'decisions' in outputs or 'response_format' not in parameters: return False
            if 'max_tokens' not in parameters: return False
        context = value.get('context_length')
        if type(context) is not int or not 1024 <= context <= 4000000: return False
        for key in ('input_usd_per_million', 'output_usd_per_million'):
            number = value.get(key)
            if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= 100000: return False
        return bool(value.get('pricing_source'))
    except (TypeError, ValueError):
        return False

def normalize(item, source, checked_at):
    architecture, pricing = item.get('architecture') or {}, item.get('pricing') or {}
    parameters = item.get('supported_parameters') or []
    model = item.get('id')
    result = {'model': model, 'label': item.get('name') or model,
              'input_modalities': architecture.get('input_modalities', []),
              'output_modalities': architecture.get('output_modalities', []),
              'vision': 'image' in architecture.get('input_modalities', []),
              'temperature_supported': 'temperature' in parameters,
              'reasoning_supported': bool({'reasoning', 'reasoning_effort', 'include_reasoning'}.intersection(parameters)),
              'supported_parameters': parameters, 'context_length': item.get('context_length'),
              'max_completion_tokens': (item.get('top_provider') or {}).get('max_completion_tokens'),
              'input_usd_per_million': round(float(pricing['prompt']) * 1000000, 8),
              'output_usd_per_million': round(float(pricing['completion']) * 1000000, 8),
              'pricing_source': source + ' (' + checked_at + ')', 'metadata_source': source, 'metadata_checked_at': checked_at,
              'pricing_overrides': [{'min_prompt_tokens': int(v['min_prompt_tokens']),
                  'input_usd_per_million': float(v['prompt']) * 1000000,
                  'output_usd_per_million': float(v['completion']) * 1000000} for v in pricing.get('overrides', [])]}
    if 'decisions' in result['output_modalities']:
        result.update(provider='openrouter', family=model.split('/')[0], response_model=item.get('canonical_slug'))
    result.update(vision_metadata().get(model,{}))
    return result

def discover(settings, kind='generative'):
    source = settings['openrouter_base_url'].rstrip('/') + '/models'
    if kind == 'decisions': source += '?output_modalities=decisions'
    response = requests.get(source, timeout=15)
    response.raise_for_status()
    data = response.json().get('data')
    if not isinstance(data, list) or len(data) > 10000: raise ValueError('Invalid provider model catalogue.')
    checked_at = datetime.now(timezone.utc).isoformat()
    result = []
    for item in data:
        try:
            value = normalize(item, source, checked_at)
            if compatible(value, kind): result.append(value)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
    return sorted(result, key=lambda v: v['label'].casefold())

def pricing_rates(model, tokens=None):
    """Use the highest tier reachable within the supplied input bound; None considers every published tier."""
    candidates = [(model['input_usd_per_million'], model['output_usd_per_million'])]
    for tier in model.get('pricing_overrides', []):
        if tokens is None or tokens >= tier['min_prompt_tokens']:
            candidates.append((tier['input_usd_per_million'], tier['output_usd_per_million']))
    return max(v[0] for v in candidates), max(v[1] for v in candidates)
