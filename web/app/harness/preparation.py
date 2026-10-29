"""Selected protocol data and shared spending contracts; never execute their contents."""
import hashlib
import re
from .contracts import ContractError, array_value, digest, number, object_value, text


def protocol_bundle(value):
    if value is None:
        return None
    value = object_value(value, 'protocol bundle')
    documents = []
    total = 0
    for item in array_value(value.get('documents'), 'protocol documents'):
        item = object_value(item, 'protocol document')
        name = text(item.get('name'), 'protocol document name', 120)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(md|json|txt)', name):
            raise ContractError('Use a plain protocol filename without directories')
        text(item.get('content'), 'protocol text', 1000000)
        content = item['content']
        raw = content.encode(); total += len(raw)
        sha = hashlib.sha256(raw).hexdigest()
        if item.get('sha256') is not None and item['sha256'] != sha:
            raise ContractError('Protocol document hash mismatch')
        documents.append({'name': name, 'content': content, 'sha256': sha})
    if not documents or len(documents) > 12 or len({d['name'] for d in documents}) != len(documents) or total > 1000000:
        raise ContractError('Select distinct protocol documents within the one-megabyte limit')
    result = {'version': text(value.get('version'), 'protocol version', 120), 'documents': documents}
    result['digest'] = digest(result)
    if value.get('digest') is not None and value['digest'] != result['digest']:
        raise ContractError('Protocol bundle hash mismatch')
    return result


def budget_group(value):
    if value is None:
        return None
    value = object_value(value, 'shared budget')
    result = {'id': text(value.get('id'), 'shared budget identifier', 120),
              'stage': text(value.get('stage'), 'shared budget stage', 120),
              'total_usd': number(value.get('total_usd'), 'shared total budget', 0, 1000000),
              'stage_limits': {text(k, 'budget stage', 120): number(v, 'stage budget', 0, 1000000)
                               for k, v in object_value(value.get('stage_limits'), 'stage budgets').items()}}
    if result['stage'] not in result['stage_limits'] or sum(result['stage_limits'].values()) > result['total_usd'] + 1e-12:
        raise ContractError('Stage limits must fit the shared total budget')
    return result


def compatible_groups(first, second):
    return first['total_usd'] == second['total_usd'] and first['stage_limits'] == second['stage_limits']
