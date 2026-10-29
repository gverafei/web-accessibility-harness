"""Decision-only catalogue; reviewed metadata is frozen separately from workers."""
import json
from .contracts import ContractError, model_snapshot
from model_catalog_metadata import compatible, discover, reviewed_metadata

CATALOG_SETTING = 'decision_model_catalog_json'
_reviewed = reviewed_metadata(kind='decisions')
# Initial choices only; validation and runtime are not restricted to this list.
DEFINITIONS = tuple(dict(_reviewed[model],id=model,label=label,enabled=enabled,is_default=enabled)
    for model,label,enabled in [('openai/gpt-6-luna-decisions','OpenAI Decisions',True),('typesafe/jev-1.13','Jev 1.13',False)])

def catalogue(settings):
    raw=settings.get(CATALOG_SETTING)
    values=validate_catalogue(json.loads(raw),reviewed_metadata(settings,'decisions')) if raw else [dict(v) for v in DEFINITIONS]
    return [dict(v,enabled=v['enabled'] and v['model']=='openai/gpt-6-luna-decisions',
                 is_default=v['is_default'] and v['model']=='openai/gpt-6-luna-decisions') for v in values]

def validate_catalogue(value, metadata=None):
    if not isinstance(value,list) or not 1 <= len(value) <= 32:raise ContractError('Keep between 1 and 32 model choices.')
    metadata = reviewed_metadata(kind='decisions') if metadata is None else metadata
    result, ids = [], set()
    for item in value:
        if not isinstance(item,dict):raise ContractError('Each model choice must be an object.')
        model = item.get('model'); definition = metadata.get(model,{})
        if not compatible(definition,'decisions'):raise ContractError('Select a discovered decision model with known context and pricing.')
        # ID is its explicit provider model, without arbitrary generative variants.
        if item.get('id') != model or model in ids:raise ContractError('Every choice needs a unique identifier.')
        ids.add(model)
        label = str(item.get('label') or definition['label']).strip()
        if not 1 <= len(label) <= 120:raise ContractError('Provide a short model name.')
        result.append(dict(definition,id=model,label=label,enabled=item.get('enabled') is True,is_default=item.get('is_default') is True))
    defaults=[v for v in result if v['is_default']]
    if len(defaults)!=1 or not defaults[0]['enabled']:raise ContractError('Choose one enabled default decision model')
    return result

def snapshot(value):
    if not isinstance(value,dict):
        raise ContractError('Select an approved decision model')
    if value.get('provider')!='openrouter':raise ContractError('Decision models use OpenRouter')
    if value.get('id') != value.get('model'):raise ContractError('Unknown decision model')
    if value.get('model') not in {d['model'] for d in DEFINITIONS} and not compatible(value,'decisions'):
        raise ContractError('Select an approved decision model')
    return model_snapshot(value,decision=True)

def discover_models(settings):
    return [model for model in discover(settings,'decisions') if model.get('vision')]


def is_decision(value):
    return isinstance(value,dict) and 'decisions' in value.get('output_modalities',[])

def capture_choices(settings):
    """Explicit vision alternatives; prefer the saved Decisions default."""
    from remediation_model_choices import model_choices
    decisions=[dict(c,name=c['label']) for c in catalogue(settings) if c['enabled'] and c.get('vision')]
    workers=[dict(c,is_default=False) for c in model_choices(settings) if c.get('vision') and c['model']=='openai/gpt-6-luna' and c.get('reasoning_effort')=='low']
    return decisions+workers
