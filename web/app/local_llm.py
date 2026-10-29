"""Explicit, external Ollama configuration; never falls back to cloud."""
from urllib.parse import urlsplit
import requests
import time
import json

LOCAL_CONTEXT_LENGTH = 32768


class LocalModelError(requests.RequestException):
    """An explicit local-provider failure; keep an already evaluated candidate."""


def ollama_endpoint(endpoint):
    endpoint = str(endpoint or '').strip().rstrip('/')
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Enter a valid Ollama HTTP/HTTPS address without credentials, query or fragment.')
    if parsed.hostname == 'ollama.com':
        raise ValueError('Use your own Ollama server, not the Ollama cloud endpoint.')
    return endpoint if endpoint.endswith('/v1') else endpoint + '/v1'


def installed_local_models(endpoint):
    base = ollama_endpoint(endpoint)
    response = requests.get(base[:-3] + '/api/tags', timeout=5)
    response.raise_for_status()
    models = response.json().get('models') or []
    if not isinstance(models, list):
        raise ValueError('Ollama returned an invalid installed-model list.')
    choices = []
    deadline = time.monotonic() + 12
    for item in models:
        remaining = deadline - time.monotonic()
        model = str(item.get('name') or item.get('model') or '') if isinstance(item, dict) else ''
        if not model or model.endswith('-cloud'):
            continue
        capabilities = []
        verified = False
        if remaining > 0:
            try:
                details = requests.post(base[:-3] + '/api/show', json={'model': model}, timeout=min(2, remaining))
                details.raise_for_status()
                capabilities = details.json().get('capabilities') or []
                verified = isinstance(capabilities, list)
            except (requests.RequestException, ValueError, AttributeError):
                pass  # One unavailable model must not hide the installed list.
        if not verified:
            capabilities = []
        choices.append({'id': model, 'name': model, 'vision': 'vision' in capabilities,
                        'capabilities': capabilities, 'capabilities_verified': verified})
    return sorted(choices, key=lambda item: item['id'])


def local_configuration(settings):
    endpoint = str(settings.get('ollama_base_url') or '').strip().rstrip('/')
    model = str(settings.get('ollama_model') or '').strip()
    if not endpoint and not model:
        return None
    base = ollama_endpoint(endpoint)
    if not model or len(model) > 200 or any(c.isspace() for c in model) or model.endswith('-cloud'):
        raise ValueError('Enter the exact installed local model name, for example llama3.1:8b (not a cloud model).')
    capabilities = json.loads(settings.get('ollama_capabilities_json') or '[]')
    # Local thinking can consume the entire output/time budget before HTML or
    # JSON appears. Comparable local pilots use explicit non-thinking mode
    # whenever the installed model advertises that capability.
    effort = 'none' if 'thinking' in capabilities else None
    return {'base_url': base, 'model': model, 'vision': 'vision' in capabilities,
            'reasoning_effort': effort, 'context_length': LOCAL_CONTEXT_LENGTH}


def local_chat(config, messages, json_mode=False, temperature=None, output_token_limit=8000):
    """Native API gives explicit context limits and forbids silent prompt loss."""
    converted = []
    for message in messages:
        content = message['content']
        item = {'role': message['role'], 'content': content}
        if isinstance(content, list):
            item['content'] = '\n'.join(block.get('text', '') for block in content if block.get('type') == 'text')
            if config.get('vision'):
                images = []
                for block in content:
                    if block.get('type') != 'image_url':
                        continue
                    url = block.get('image_url', {}).get('url', '')
                    if not url.startswith('data:image/') or ';base64,' not in url:
                        raise ValueError('Local visual references must be acquired base64 image captures; remote image URLs are not fetched.')
                    images.append(url.split(';base64,', 1)[1])
                if images:
                    item['images'] = images
        converted.append(item)
    payload = {'model': config['model'], 'messages': converted,
               'stream': True, 'truncate': False, 'shift': False,
               'options': {'num_ctx': int(config.get('context_length') or LOCAL_CONTEXT_LENGTH),
                           'num_predict': int(output_token_limit)}}
    if temperature is not None:
        payload['options']['temperature'] = temperature
    if json_mode:
        payload['format'] = 'json'
    if config.get('reasoning_effort'):
        payload['think'] = False if config['reasoning_effort'] == 'none' else config['reasoning_effort']
    base = ollama_endpoint(config['base_url'])[:-3]
    response = requests.post(base + '/api/chat', json=payload, timeout=(10, 300), stream=True)
    try:
        if response.status_code == 400:
            raise LocalModelError('Ollama rejected the complete local context: ' + str(response.json().get('error') or 'invalid request'), response=response)
        response.raise_for_status()
        parts = []
        for line in response.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
            except (ValueError, TypeError) as error:
                raise LocalModelError('Ollama returned an invalid streaming response', response=response) from error
            if not isinstance(data, dict):
                raise LocalModelError('Ollama returned a non-object streaming response', response=response)
            if data.get('error'):
                raise LocalModelError('Ollama generation failed: ' + str(data['error']), response=response)
            message = data.get('message') or {}
            content = message.get('content') if isinstance(message, dict) else None
            if content is not None and not isinstance(content, str):
                raise LocalModelError('Ollama returned non-text message content', response=response)
            parts.append(content or '')
            if data.get('done'):
                content = ''.join(parts)
                if not content:
                    raise LocalModelError('Ollama returned no content', response=response)
                return content, int(data.get('prompt_eval_count') or 0), int(data.get('eval_count') or 0)
        raise LocalModelError('Ollama stream ended before completion; partial output was not applied', response=response)
    finally:
        response.close()


def local_choice(settings):
    config = local_configuration(settings)
    if config is None:
        return None
    return {'id': 'ollama/' + config['model'], 'name': config['model'],
            'temperature_supported': True, 'vision': config['vision'],
            'tier': 'local', 'color': '#64748b', 'reasoning_effort': config['reasoning_effort'],
            'provider': 'ollama'}
