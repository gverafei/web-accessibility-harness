"""Versioned inputs shared by GUI, worker and offline reanalysis."""
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

SCHEMA = 'a11yharness/1'
STATES = ('passed', 'violated', 'unverified', 'not_applicable')
MODES = ('development', 'frozen', 'longitudinal')
CRITERIA = {
    'content': 'Protected text, facts, reading order and media meaning are preserved.',
    'tasks': 'Controls, actions, destinations and acquired interactions retain their purpose.',
    'names': 'Added accessible names and alternatives are supported by page context.',
    'structure': 'Headings, landmarks and relationships express the acquired content correctly.',
}


def semantic_status(result):
    values = [result.get(key, {}).get('status') for key in CRITERIA]
    if 'violated' in values:
        return 'violated'
    return 'passed' if all(value in ('passed', 'not_applicable') for value in values) else 'unverified'


class ContractError(ValueError):
    pass

class MeasurementIncomplete(ContractError):
    """A technical measurement failure prevents a completed study result."""
    pass


class ModelOutputIncomplete(ContractError):
    """A received, accounted response without usable completion text."""
    def __init__(self, reason, usage, call_id=None, response_id=None):
        super().__init__('Worker output incomplete: ' + reason)
        self.reason = reason
        self.usage = usage
        self.call_id = call_id
        self.response_id = response_id


def canonical(value):
    # Browser JSON may contain a lone UTF-16 code unit after bounded text
    # slicing. Preserve it as a JSON escape, rather than dropping evidence or
    # replacing it with a guessed character. Valid Unicode retains its bytes.
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if not re.search(r'[\ud800-\udfff]', serialized):
        return serialized
    serialized = serialized.encode('utf-16-le', 'surrogatepass').decode('utf-16-le', 'surrogatepass')
    return re.sub(r'[\ud800-\udfff]', lambda match: '\\u' + format(ord(match[0]), '04x'), serialized)


def decode_json(value):
    """Accept one JSON document, optionally in a single complete Markdown fence."""
    if not isinstance(value, str):
        return value
    value = value.strip()
    fence = re.fullmatch(r'```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```', value, re.IGNORECASE)
    if fence:
        value = fence[1]
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ContractError('Invalid structured JSON response') from error


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def number(value, name, low=0, high=None, integer=False):
    if isinstance(value, bool):
        raise ContractError(f'{name}: a number is required')
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ContractError(f'{name}: a number is required') from error
    if not math.isfinite(result) or result < low or high is not None and result > high or integer and result != int(result):
        raise ContractError(f'{name}: outside its allowed range')
    return int(result) if integer else result


def text(value, name, maximum=240):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ContractError(f'{name}: nonempty text of at most {maximum} characters is required')
    return value.strip()


def public_url(value):
    value = text(value, 'URL', 4000)
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ContractError('Use an HTTP(S) URL without embedded credentials')
    return value


def object_value(value, name):
    if not isinstance(value, dict):
        raise ContractError(name + ': an object is required')
    return value


def array_value(value, name):
    if not isinstance(value, list):
        raise ContractError(name + ': an array is required')
    return value


def model_snapshot(value,decision=False):
    if not isinstance(value, dict):
        raise ContractError('Model configuration must be an object')
    result = {k:v for k,v in value.items() if k in ('id','model','provider','family','context_length','max_completion_tokens','input_usd_per_million','output_usd_per_million','pricing_source','vision','temperature_supported','reasoning_effort','input_modalities','output_modalities','supported_parameters','pricing_overrides','vision_token_bounds','vision_pricing_source')}
    result['id'] = text(value.get('id'), 'model choice')
    result['model'] = text(value.get('model'), 'model')
    if not decision and ('decisions' in value.get('output_modalities',[]) or result['model'] in ('openai/gpt-6-luna-decisions','typesafe/jev-1.13')):
        raise ContractError('Decision models cannot generate repairs or judge rationales')
    result['provider'] = value.get('provider', 'openrouter')
    if result['provider'] not in ('openrouter', 'ollama') or result['model'].startswith('openrouter/'):
        raise ContractError('Select an explicit supported model, not automatic routing')
    if result['provider']=='ollama' and not value.get('family'): raise ContractError('Declare the actual local model family, not the provider name')
    if 'provider_route' in value:
        route = object_value(value['provider_route'], 'provider route')
        required = {'only', 'allow_fallbacks', 'require_parameters'}
        if result['provider'] != 'openrouter' or not required <= set(route) or set(route)-required-{'max_price'}:
            raise ContractError('Invalid frozen provider route')
        providers = route['only']
        if (not isinstance(providers, list) or not 1 <= len(providers) <= 8 or
                any(not isinstance(p, str) or not re.fullmatch(r'[A-Za-z0-9_./-]{1,100}', p) for p in providers) or
                route['allow_fallbacks'] is not False or route['require_parameters'] is not True):
            raise ContractError('Frozen provider route requires explicit providers and no fallback')
        frozen_route = {'only': list(providers), 'allow_fallbacks': False, 'require_parameters': True}
        if 'max_price' in route:
            prices = object_value(route['max_price'], 'provider price limits')
            if set(prices) != {'prompt', 'completion'}:
                raise ContractError('Specify prompt and completion price limits')
            frozen_route['max_price'] = {k:number(v, 'provider price limit', 0, 100000) for k,v in prices.items()}
        result['provider_route'] = frozen_route
    result['family'] = text(value.get('family') or result['model'].split('/')[0], 'model family')
    if result['provider']=='openrouter' and ('/' not in result['model'] or result['family']!=result['model'].split('/')[0]):
        raise ContractError('Cloud family must match the explicit provider model namespace')
    if decision and value.get('response_model'):
        result['response_model'] = text(value['response_model'], 'frozen response model')
        if result['response_model'].split('/')[0] != result['family']:
            raise ContractError('Frozen response identity must belong to the selected family')
    result['context_length'] = number(value.get('context_length') or 32768, 'context length', 1024, 4000000, True)
    if 'vision_token_bounds' in value:
        bounds=object_value(value['vision_token_bounds'],'image token bounds')
        if not bounds or set(bounds)-{'auto','original','high','low'}:raise ContractError('Unknown image detail bound')
        result['vision_token_bounds']={k:number(v,'image token bound',1,4000000,True) for k,v in bounds.items()}
        result['vision_pricing_source']=text(value.get('vision_pricing_source'),'image pricing source',1000)
    for key in ('input_usd_per_million', 'output_usd_per_million'):
        result[key] = number(value.get(key, 0 if result['provider'] == 'ollama' else None), key, 0, 100000)
    if 'pricing_overrides' in value:
        tiers=value['pricing_overrides']
        if not isinstance(tiers,list) or len(tiers)>32:raise ContractError('Invalid pricing tiers')
        result['pricing_overrides']=[{'min_prompt_tokens':number(t['min_prompt_tokens'],'price threshold',0,4000000,True),
            'input_usd_per_million':number(t['input_usd_per_million'],'input rate',0,100000),
            'output_usd_per_million':number(t['output_usd_per_million'],'output rate',0,100000)} for t in tiers]
    result['pricing_source'] = text(value.get('pricing_source') or ('local provider; no API charge' if result['provider'] == 'ollama' else 'user-declared pricing snapshot'), 'pricing source', 1000)
    result['schema'] = SCHEMA
    result['digest'] = digest({k: v for k, v in result.items() if k != 'digest'})
    return result


def budget(value):
    if not isinstance(value, dict):
        raise ContractError('Resource limits must be configured')
    result = {
        'max_cost_usd': number(value.get('max_cost_usd'), 'cost budget', 0, 100000),
        'max_seconds': number(value.get('max_seconds'), 'time budget', 1, 86400),
        'max_calls': number(value.get('max_calls'), 'call budget', 1, 10000, True),
        'max_output_tokens': number(value.get('max_output_tokens', 8192), 'output tokens', 32, 1000000, True),
    }
    if value.get('max_call_cost_usd') is not None:
        result['max_call_cost_usd'] = number(value['max_call_cost_usd'], 'per-call cost budget', 0, 100000)
    return result


def validate_manifest(value):
    if not isinstance(value, dict):
        raise ContractError('Campaign manifest must be an object')
    result = {k:v for k,v in value.items() if k in ('name','study_id','seed','mode','partition','source','workers','judges','repetitions','max_iterations','repair_budget','review_budget','campaign_cost_limit','targets','conditions','corpus_id','retriever','top_k','author_sample_count','policy_id','orchestrator','evaluator','rag_contrast','oracle_benchmark_id','promotion_thresholds','analysis','capture_only','oracle_benchmark_ids','review_prioritization','capture_verifier','category_review_model')}
    if 'diagnosis_policy' in value:
        if value['diagnosis_policy'] not in ('disabled', 'adaptive', 'always'):
            raise ContractError('Invalid diagnosis policy')
        result['diagnosis_policy'] = value['diagnosis_policy']
    if 'time_policy' in value:
        from .time_policy import ITERATION_BOUNDARY,BUDGET_PROGRESS,CANDIDATE_BOUNDARY
        if value['time_policy'] not in (ITERATION_BOUNDARY,BUDGET_PROGRESS,CANDIDATE_BOUNDARY):
            raise ContractError('Invalid time policy')
        result['time_policy'] = value['time_policy']
    if 'iteration_policy' in value:
        from .iteration_policy import VERSION
        if value['iteration_policy'] != VERSION:
            raise ContractError('Invalid iteration policy')
        result['iteration_policy'] = VERSION
    if 'native_control_state_required' in value:
        if not isinstance(value['native_control_state_required'],bool):
            raise ContractError('Native control state requirement must be a boolean')
        result['native_control_state_required']=value['native_control_state_required']
    if 'source_repeatability_required' in value:
        if not isinstance(value['source_repeatability_required'],bool):
            raise ContractError('Source repeatability requirement must be boolean')
        result['source_repeatability_required']=value['source_repeatability_required']
    for key,allowed in (('candidate_review_mode',{'gate','diagnostic-only'}),
                        ('refinement_policy',{'decision-guided','bounded-feedback','budget-only-progress'})):
        if key in value:
            if not isinstance(value[key],str) or value[key] not in allowed:raise ContractError('Invalid '+key)
            result[key]=value[key]
    if 'stop_at_perfect_audit' in value:
        if not isinstance(value['stop_at_perfect_audit'], bool):
            raise ContractError('Perfect-audit stopping must be a boolean')
        result['stop_at_perfect_audit'] = value['stop_at_perfect_audit']
    if 'attempt_limit' in value:
        result['attempt_limit']=number(value['attempt_limit'],'attempt limit',1,1000,True)
    if 'max_generation_attempts_per_candidate' in value:
        if 'iteration_policy' not in result:
            raise ContractError('Per-candidate attempt limits require evaluated-candidate counting')
        result['max_generation_attempts_per_candidate'] = number(
            value['max_generation_attempts_per_candidate'], 'Attempts per candidate', 1, 1000, True)
    if 'worker_prompt_policy' in value:
        from .prompt_policy import VERSION as PROMPT_POLICY
        if value['worker_prompt_policy'] != PROMPT_POLICY:
            raise ContractError('Unknown worker prompt policy')
        result['worker_prompt_policy'] = PROMPT_POLICY
    if value.get('experience_library_id') or value.get('record_experience'):
        raise ContractError('Cross-run remediation history is unavailable')
    if any(value.get(key) for key in ('adaptive_plan_version', 'adaptive_planner_model',
            'adaptive_planner_protocol', 'adaptive_route_cost_version',
            'adaptive_resource_policy_version', 'adaptive_resource_priorities_version',
            'adaptive_planner_selection_id', 'adaptive_planner_selection_hash')):
        raise ContractError('Historical route planning is retired; use page-guided Decisions')
    if 'adaptive_evidence_version' in value:
        from .dynamic_objectives import SUPPORTED_EVIDENCE_VERSIONS
        if value['adaptive_evidence_version'] not in SUPPORTED_EVIDENCE_VERSIONS:
            raise ContractError('Unknown adaptive role evidence contract')
        result['adaptive_evidence_version'] = value['adaptive_evidence_version']
    if 'patch_validation_version' in value:
        from coordinated_role_validation import SUPPORTED_VERSIONS as PATCH_VALIDATION_VERSIONS
        if value['patch_validation_version'] not in PATCH_VALIDATION_VERSIONS:
            raise ContractError('Unknown patch validation contract')
        result['patch_validation_version'] = value['patch_validation_version']
    if 'adaptive_patch_context_version' in value:
        from grounded_patch_context import SUPPORTED_VERSIONS as COVERAGE_VERSIONS
        if value['adaptive_patch_context_version'] not in COVERAGE_VERSIONS:
            raise ContractError('Unknown target coverage contract')
        from .adaptive_repair_context import SUPPORTED_VERSIONS as COORDINATED_VERSIONS
        if result.get('adaptive_evidence_version') not in COORDINATED_VERSIONS:
            raise ContractError('Target coverage requires complete coordinated evidence')
        result['adaptive_patch_context_version'] = value['adaptive_patch_context_version']
    if 'record_experience' in value:
        if not isinstance(value['record_experience'], bool):
            raise ContractError('Experience recording must be boolean')
        result['record_experience'] = value['record_experience']
    if 'frozen_source_binding' in value:
        binding=object_value(value['frozen_source_binding'],'frozen source binding')
        from .source_binding import VERSION as BINDING_VERSION
        if binding.get('version')!=BINDING_VERSION:
            raise ContractError('Invalid frozen source binding version')
        allowed={'version','sql_source_id','capture_id','audit_id','replay_id','source_artifact_id','input_sha256','native_package_sha256','reference_document_sha256','evaluator_runtime_sha256','preflight_basis'}
        if set(binding)-allowed:
            raise ContractError('Unknown frozen source binding field')
        binding=dict(binding)
        if 'preflight_basis' in binding:
            binding['preflight_basis']=text(binding['preflight_basis'],'binding preflight basis',240)
        binding['sql_source_id']=number(binding.get('sql_source_id'),'bound acquisition',1,1000000000,True)
        for key in ('capture_id','audit_id','replay_id','source_artifact_id'):
            binding[key]=text(binding.get(key),'bound '+key,240)
        for key in ('input_sha256','native_package_sha256','reference_document_sha256','evaluator_runtime_sha256'):
            if not isinstance(binding.get(key),str)or not re.fullmatch('[0-9a-f]{64}',binding[key]):
                raise ContractError('Invalid frozen source binding digest: '+key)
        result['frozen_source_binding']=binding
        if 'source_binding_scope' in value:
            result['source_binding_scope']=text(value['source_binding_scope'],'source binding scope',120)
    elif 'source_binding_scope' in value:
        raise ContractError('Source binding scope requires its frozen binding')
    if 'intervention_version' in value:
        from remediation_interventions import validate_version
        try: result['intervention_version']=validate_version(value['intervention_version'])
        except ValueError as error: raise ContractError(str(error)) from error
    result['schema'] = SCHEMA
    result['name'] = text(value.get('name'), 'campaign name', 120)
    result['study_id'] = text(value.get('study_id'), 'study identifier', 120)
    result['seed'] = text(str(value.get('seed', '')), 'seed', 240)
    result['mode'] = value.get('mode', 'frozen')
    if result['mode'] not in MODES:
        raise ContractError('Unknown learning mode')
    result['partition'] = value.get('partition', 'test' if result['mode'] == 'frozen' else 'development')
    if result['partition'] not in ('development', 'validation', 'test', 'longitudinal'):
        raise ContractError('Unknown data partition')
    if result['mode'] == 'development' and result['partition'] != 'development' or result['mode'] == 'longitudinal' and result['partition'] != 'longitudinal':
        raise ContractError('Learning mode and data partition are incompatible')
    source = object_value(value.get('source'), 'source')
    result['source'] = {k:v for k,v in source.items() if k in ('kind','page_ids','urls','count','reserve_count','list_id','curated_id','selection')}
    if result['source'].get('kind') not in ('tranco', 'urls','snapshots','curated'):
        raise ContractError('Select Tranco, explicit URLs or existing frozen snapshots')
    if result['source']['kind']=='curated':
        result['source']={'kind':'curated','curated_id':text(source.get('curated_id'),'curated snapshot'),
            'count':number(source.get('count'),'curated pages',1,1000000,True),'selection':source.get('selection','seeded'),'reserve_count':0}
        if result['source']['selection'] not in ('seeded','ranked'):raise ContractError('Unknown curated selection')
    elif result['source']['kind'] == 'snapshots':
        pages=array_value(result['source'].get('page_ids',[]),'snapshot IDs')
        pages=[text(p,'snapshot ID') for p in pages]
        if not pages or len(set(pages))!=len(pages): raise ContractError('Choose distinct frozen page snapshots')
        result['source']={'kind':'snapshots','page_ids':[text(p,'snapshot ID') for p in pages],'count':len(pages)}
    elif result['source']['kind'] == 'urls':
        urls = [public_url(url) for url in array_value(result['source'].get('urls', []),'URLs')]
        if not urls or len(set(urls)) != len(urls):
            raise ContractError('Provide unique page URLs')
        result['source']['urls'] = urls
        result['source']['count'] = len(urls)
    else:
        result['source']['count'] = number(result['source'].get('count'), 'Tranco pages', 1, 1000000, True)
        result['source']['reserve_count'] = number(result['source'].get('reserve_count', 0), 'reserve pages', 0, 1000000, True)
        list_id = str(result['source'].get('list_id') or 'latest')
        if list_id != 'latest' and not re.fullmatch(r'[A-Za-z0-9]{3,20}', list_id):
            raise ContractError('Invalid Tranco list identifier')
        result['source']['list_id'] = list_id
    workers = [model_snapshot(model) for model in array_value(value.get('workers', []),'workers')]
    if not workers or len({m['id'] for m in workers}) != len(workers):
        raise ContractError('Select distinct approved worker choices')
    result['workers'] = workers
    if value.get('judges') or value.get('author_sample_count') or value.get('author_enriched_count'):
        raise ContractError('Core pilots use technical checks; independent review is deferred')
    result.pop('judges', None)
    result.pop('author_sample_count', None)
    result.pop('review_prioritization', None)
    from remediation_interventions import VERSION as CURRENT_INTERVENTIONS
    result['evaluation_basis'] = 'observable-candidate-usability-v1'if result.get('intervention_version')==CURRENT_INTERVENTIONS else'observable-technical-v1'
    result['measurement_basis'] = 'response-native-resources-desktop-v4'
    from .categories import category_vocabulary
    result['category_vocabulary']=category_vocabulary(value.get('category_vocabulary',[]))
    from .decision_models import is_decision, snapshot as decision_snapshot
    result['capture_verifier']=(decision_snapshot(value['capture_verifier']) if is_decision(value['capture_verifier']) else model_snapshot(value['capture_verifier'])) if value.get('capture_verifier') else None
    if result['capture_verifier'] and not result['capture_verifier'].get('vision'):raise ContractError('Capture verifier must support images')
    result['category_review_model']=decision_snapshot(value['category_review_model']) if value.get('category_review_model') else None
    result['repetitions'] = number(value.get('repetitions', 1), 'repetitions', 1, 1000, True)
    result['max_iterations'] = number(value.get('max_iterations', 3), 'iterations', 1, 1000, True)
    result['repair_budget'] = budget(value.get('repair_budget'))
    result['review_budget'] = budget(value.get('review_budget'))
    result['campaign_cost_limit'] = number(value.get('campaign_cost_limit'), 'campaign cost limit', 0, 1000000)
    targets = object_value(value.get('targets',{}),'targets')
    result['targets'] = {'max_axe': number(targets.get('max_axe', 3), 'Axe target', 0, 1000000, True),
                         'min_lighthouse': number(targets.get('min_lighthouse', 94), 'Lighthouse target', 0, 100)}
    conditions = array_value(value.get('conditions') or [],'conditions')
    ids = set()
    conditions = [{k:v for k,v in object_value(c,'condition').items() if k in ('id','level','public_level','worker_id','selector','rag','arm','controls','policy_id','guidance_policy_id','memory_policy_id','fixed_level','retriever')} for c in conditions]
    for condition in conditions:
        ident = text(condition.get('id'), 'condition id')
        if ident in ids:
            raise ContractError('Condition identifiers must be unique')
        ids.add(ident)
        condition['level'] = number(condition.get('level'), 'intervention', 1, 6, True)
        from remediation_interventions import VERSION as CURRENT_INTERVENTIONS, wire_to_public, four_policy
        if four_policy(result.get('intervention_version')):
            try: public=wire_to_public(condition['level'])
            except ValueError as error: raise ContractError(str(error)) from error
            if type(condition.get('public_level',public))is not int or condition.get('public_level',public)!=public:
                raise ContractError('Public intervention and wire policy differ')
            condition['public_level']=public
        elif 'public_level' in condition:
            raise ContractError('Public policy numbering requires its versioned contract')
        if condition.get('rag', 'retrieved') not in ('retrieved', 'off', 'oracle'):
            raise ContractError('Unknown RAG condition')
        if condition.get('selector', 'rules') not in ('rules', 'decisions', 'structured', 'linucb', 'fixed', 'round_robin', 'initial'):
            raise ContractError('Unknown action selector')
        if condition.get('worker_id') not in {w['id'] for w in workers}:
            raise ContractError('Condition worker is outside the approved pool')
        if condition.get('rag', 'retrieved') != 'retrieved' and (not value.get('rag_contrast') or result['mode'] != 'frozen'):
            raise ContractError('RAG off/oracle requires a frozen paired contrast')
        if condition.get('arm', 'standard') not in ('standard', 'control', 'learning'):
            raise ContractError('Unknown longitudinal arm')
        flags = object_value(condition.get('controls', {}),'controls')
        if set(flags) - {'preservation', 'retention', 'feedback', 'guidance', 'memory'} or any(type(v) is not bool for v in flags.values()):
            raise ContractError('Unknown or invalid controller ablation')
    if not conditions:
        raise ContractError('Select experimental conditions')
    if result['mode'] == 'longitudinal' and not {'control', 'learning'} <= {c.get('arm') for c in conditions}:
        raise ContractError('Longitudinal campaigns require paired control and learning arms')
    if result['mode']=='longitudinal':
        if len(conditions)!=2 or len({canonical({k:v for k,v in c.items() if k not in ('id','arm')}) for c in conditions})!=1:
            raise ContractError('Use one matched longitudinal control/learning pair; separate studies must have separate campaign histories')
    for c in conditions:
        if c.get('retriever') and c['retriever'] not in ('legacy','mapped','decisions'): raise ContractError('Unknown condition retriever')
        if c.get('fixed_level') is not None: c['fixed_level']=number(c['fixed_level'],'fixed intervention',1,5,True)
        for key in ('policy_id','guidance_policy_id','memory_policy_id'):
            if c.get(key): c[key]=text(c[key],key)
    result['conditions'] = conditions
    result['corpus_id'] = text(value.get('corpus_id'), 'frozen corpus identifier')
    result['retriever'] = value.get('retriever', 'mapped')
    if result['retriever'] not in ('legacy', 'mapped', 'decisions'):
        raise ContractError('Unknown retriever')
    result['top_k'] = number(value.get('top_k', 4), 'example count', 2, 12, True)
    if result['top_k'] % 2:
        raise ContractError('Use an even count to preserve complete passed/failed pairs')
    result['capture_only']=value.get('capture_only') is True
    result['provider_probe']=value.get('provider_probe') is True
    if result['provider_probe'] and result['capture_only']:raise ContractError('Choose contract checks or page acquisition, not both')
    result['oracle_benchmark_ids']=[text(i,'oracle reference') for i in array_value(value.get('oracle_benchmark_ids',[]),'oracle references')]
    result['policy_id'] = value.get('policy_id') or None
    result['orchestrator'] = model_snapshot(value['orchestrator']) if value.get('orchestrator') else None
    from .decision_models import snapshot as decision_snapshot
    result['decision_model']=decision_snapshot(value['decision_model']) if value.get('decision_model') else None
    if value.get('contextual_judge_model'):
        from accessibility_taxonomy.contextual_judge import VERSION as JUDGE_PROTOCOL, DECISIONS_PROTOCOL, validate as judge_snapshot, MIN_OUTPUT_TOKENS
        protocol = value.get('contextual_judge_protocol')
        if protocol not in (JUDGE_PROTOCOL, DECISIONS_PROTOCOL):
            raise ContractError('Unknown frozen contextual judge protocol')
        result['contextual_judge_model'] = (judge_snapshot(value['contextual_judge_model'])
            if protocol == JUDGE_PROTOCOL else decision_snapshot(value['contextual_judge_model']))
        result['contextual_judge_protocol'] = protocol
        if protocol == DECISIONS_PROTOCOL and result['contextual_judge_model'] != result['decision_model']:
            raise ContractError('The contextual Decisions judge must match its frozen decision model')
        if protocol == JUDGE_PROTOCOL and result['review_budget']['max_output_tokens'] < MIN_OUTPUT_TOKENS:
            raise ContractError('Luna high contextual review needs its declared reasoning output allowance')
    if value.get('image_judge_model'):
        from accessibility_taxonomy.image_evidence import validate_model
        from accessibility_taxonomy.image_review import VERSION as IMAGE_PROTOCOL
        if value.get('image_judge_protocol') != IMAGE_PROTOCOL:
            raise ContractError('Unknown frozen image judge protocol')
        result['image_judge_model'] = validate_model(value['image_judge_model'])
        result['image_judge_protocol'] = IMAGE_PROTOCOL
    if result.get('contextual_judge_protocol') == 'decisions-contextual-choice-v1' and not result.get('image_judge_model'):
        raise ContractError('The explicit Decisions contextual role requires a frozen image judge')
    if (result['provider_probe'] or any(c.get('selector')=='decisions' or c.get('retriever')=='decisions' for c in conditions) or result['retriever']=='decisions') and not result['decision_model']:
        raise ContractError('Select an enabled decision model')
    if any(c.get('selector') == 'structured' for c in conditions) and not result['orchestrator']:
        raise ContractError('Select the structured orchestrator model')
    evaluator=object_value(value.get('evaluator') or {'axe_standard': 'wcag22aa'},'evaluator')
    if evaluator.get('axe_standard','wcag22aa') not in ('wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa'):
        raise ContractError('Choose a supported WCAG audit standard')
    result['evaluator']={'axe_standard':evaluator.get('axe_standard','wcag22aa')}
    thresholds=object_value(value.get('promotion_thresholds') or {},'promotion thresholds')
    result['promotion_thresholds']={'minimum_gain':number(thresholds.get('minimum_gain',0),'minimum gain',-1,1),
                                 'maximum_harm_increase':number(thresholds.get('maximum_harm_increase',0),'maximum harm increase',-1,1)}
    analysis=object_value(value.get('analysis',{}),'analysis')
    result['analysis']={'cost_reference':number(analysis.get('cost_reference',1),'common PRE cost reference',.000001),
       'time_reference':number(analysis.get('time_reference',180),'common PRE time reference',1),
       'axe_weight':number(analysis.get('axe_weight',.5),'PRE Axe weight',0,1),
       'contrasts':[{k:v for k,v in object_value(c,'contrast').items() if k in ('first','second','hypothesis')} for c in array_value(analysis.get('contrasts',[]),'contrasts')]}
    for contrast in result['analysis']['contrasts']:
        if contrast.get('first') not in ids or contrast.get('second') not in ids or contrast.get('first')==contrast.get('second'):
            raise ContractError('Predeclared contrast needs two distinct configured conditions')
        if contrast.get('hypothesis') not in ('H1','H2','H3','H4','H5','H6','H7','exploratory'):
            raise ContractError('Unknown hypothesis identifier')
    from .preparation import protocol_bundle, budget_group
    if value.get('protocol_bundle') is not None: result['protocol_bundle'] = protocol_bundle(value['protocol_bundle'])
    if value.get('budget_group') is not None: result['budget_group'] = budget_group(value['budget_group'])
    result['digest'] = digest({k: v for k, v in result.items() if k != 'digest'})
    return result
