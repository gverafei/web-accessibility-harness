"""Configurable offline pilot recipes. No HTTP, catalogue write or launch authority."""
import copy
import random
from .contracts import ContractError, digest, model_snapshot, number, validate_manifest
from .decision_models import DEFINITIONS
from .preparation import protocol_bundle, budget_group
from .probe_contracts import worker_request, decision_request


def build(metadata, protocol=None, *, seed='20261008', count=10, reserves=10,
          worker_ids=('openai/gpt-6-luna','anthropic/claude-haiku-5.5'),
          capture_verifier_id=None,
          fixed_worker_ids=None, decision_model=None, probe_output_tokens=4096, verification_output_tokens=4096,
          stage_limits=None, group_id='pilot-20261008', repeats=2, rag_queries=5, collection_size=20):
    count=number(count,'pilot pages',1,1000000,True)
    repeats=number(repeats,'repeat pages',0,count,True)
    rag_queries=number(rag_queries,'RAG queries',1,count,True)
    limits=stage_limits or {'connection':1,'remediation':17,'rag':6,'learning':6}
    group=budget_group({'id':group_id,'stage':'connection','total_usd':sum(limits.values()),'stage_limits':limits})
    def model(ident):
        if ident not in metadata: raise ContractError('Model metadata is unavailable: '+ident)
        actual=metadata[ident].get('model',ident)
        return model_snapshot({**metadata[ident],'id':ident,'model':actual,'provider':'openrouter','family':actual.split('/')[0]})
    workers=[model(i) for i in worker_ids]
    capture_verifier=model(capture_verifier_id) if capture_verifier_id else None
    fixed=list(fixed_worker_ids or worker_ids[:2])
    if not 2<=len(workers)<=32 or len({w['id'] for w in workers})!=len(workers) or len(fixed)!=2 or len(set(fixed))!=2 or not set(fixed)<=set(worker_ids):
        raise ContractError('Select a worker pool, two fixed configurations from that pool and a compatible capture verifier')
    fixed_workers=[next(w for w in workers if w['id']==i) for i in fixed]
    decision=decision_model or next(dict(d) for d in DEFINITIONS if d['id']=='openai/gpt-6-luna-decisions')
    probe_output_tokens=number(probe_output_tokens,'probe output tokens',128,1000000,True)
    verification_output_tokens=number(verification_output_tokens,'capture verification output tokens',512,1000000,True)
    constant={'guidance':False,'memory':False,'preservation':True,'retention':True,'feedback':True}
    conditions=[{'id':f'P{level}-W{w+1}','level':level,'worker_id':worker['id'],'selector':'rules',
                 'rag':'retrieved','controls':dict(constant)} for level in range(1,6) for w,worker in enumerate(fixed_workers)]
    conditions += [{'id':'P6-'+selector,'level':6,'worker_id':fixed_workers[0]['id'],'selector':selector,
                    'rag':'retrieved','controls':dict(constant)} for selector in ('rules','decisions','structured')]
    base={'name':'Pilot','study_id':group_id,'seed':str(seed),'mode':'frozen','partition':'development',
          'source':{'kind':'snapshots','page_ids':[]},'workers':workers,'capture_verifier':capture_verifier,
          'decision_model':decision,'orchestrator':fixed_workers[0],'repetitions':1,'max_iterations':2,
          'campaign_cost_limit':limits['remediation'],
          'repair_budget':{'max_cost_usd':limits['remediation'],'max_seconds':360,'max_calls':12,'max_output_tokens':4096},
          'review_budget':{'max_cost_usd':limits['remediation'],'max_seconds':360,'max_calls':12,'max_output_tokens':verification_output_tokens},
          'targets':{'max_axe':3,'min_lighthouse':94},'conditions':conditions,'corpus_id':None,
          'retriever':'mapped','top_k':4,
          'evaluator':{'axe_standard':'wcag22aa'},'protocol_bundle':protocol_bundle(protocol),
          'analysis':{'cost_reference':1,'time_reference':360,'axe_weight':.5,
                      'contrasts':[{'first':'P6-rules','second':'P6-'+v,'hypothesis':'H7'} for v in ('decisions','structured')]}}
    stages={}
    def stage(name, label, conditions=None, **extra):
        m=copy.deepcopy(base);m.update(name='Pilot · '+name,**extra)
        if conditions is not None:
            m['conditions']=copy.deepcopy(conditions)
            ids={c['id'] for c in conditions}
            m['analysis']['contrasts']=[c for c in m['analysis']['contrasts'] if {c['first'],c['second']} <= ids]
        m['budget_group']=dict(group,stage=label)
        m['campaign_cost_limit']=limits[label]
        for account in ('repair_budget','review_budget'):m[account]['max_cost_usd']=limits[label]
        stages[name]={'status':'pending_dependencies','requires':[],'manifest':m}
        return stages[name]
    acquisition=stage('acquisition','connection',conditions[:1],capture_only=True,
        source={'kind':'tranco','count':count,'reserve_count':number(reserves,'reserves',0,1000000,True),'list_id':None})
    acquisition['requires']=['attributed_corpus_id','pinned_tranco_list_id','approved_acquisition_manifest']
    core=stage('matrix','remediation');core['requires']=['acquired_page_ids','provider_contract_checks','approved_manifest']
    repeat=stage('repeat','remediation');repeat['requires']=['seed_selected_repeat_page_ids','approved_manifest']
    for method in ('legacy','mapped','decisions'):
        rank=stage('retrieval-'+method,'rag',conditions[:1],capture_only=True,retriever=method)
        rank['requires']=['seed_selected_rag_page_ids','approved_manifest']
    rag=[dict(conditions[0],id='RAG-'+v,rag=v) for v in ('off','retrieved','oracle')]
    effect=stage('rag-effect','rag',rag,rag_contrast=True)
    effect['requires']=['seed_selected_rag_page_ids','five_adjudicated_relevance_references','approved_manifest']
    learning=[dict(conditions[0],id='learning-observed-P1',controls=dict(constant,memory=True)),
              dict(conditions[-1],id='learning-LinUCB',selector='linucb',controls=dict(constant,memory=True))]
    train=stage('learning','learning',learning,mode='development')
    train['requires']=['acquired_page_ids','approved_manifest']
    freeze=stage('frozen-check','learning',[dict(learning[-1],id='frozen-LinUCB')])
    freeze['requires']=['evaluated_learned_policy_id','seed_selected_repeat_page_ids','approved_manifest']
    probe=stage('connection','connection',conditions[:1],source={'kind':'urls','urls':['https://example.com/']})
    probe['status']='probe_recipe_only';probe['requires']=['attributed_corpus_id','explicit_probe_approval']
    probe['checks']=['one minimal typed worker request per worker',
       'one named closed-choice Decisions request','exact identity and reported receipt before parsing',
       'recorded-result recovery without a second charge; unresolved charge blocks all stages']
    # Connection is a probe recipe, never a repair campaign launched by this builder.
    probe['manifest']['provider_probe']=True
    probe['manifest']['repair_budget']['max_output_tokens']=probe_output_tokens
    probe['manifest']['review_budget']['max_output_tokens']=verification_output_tokens
    probe['configuration']={'name':'Pilot · connection contracts','study_id':group_id,
        'budget_group':dict(group,stage='connection'),'campaign_cost_limit':limits['connection'],
        'workers':workers,'capture_verifier':capture_verifier,'decision_model':decision,'protocol_bundle':base['protocol_bundle'],
        'provenance':'synthetic contract probes; excluded from page-remediation outcomes'}
    probe['requests']=[{'role':'worker','model':m,'max_output_tokens':probe_output_tokens,**worker_request(),
        'expected_contract':'P1 typed operations: set_attribute selector img name alt value Page photo'} for m in workers]
    probe['requests'].append({'role':'decision','model':decision,'max_output_tokens':0,
        **decision_request(),
        'expected_contract':'typed named choice, exact identity and provider-reported receipt before parsing'})
    result={'schema':'a11yharness/pilot-preparation/1','status':'prepared_not_authorized','seed':str(seed),
            'sampling':{'count':count,'reserves':reserves,'replacement':'ordered, recorded failures; no expansion'},
            'rag_benchmark':{'queries':rag_queries,'collection_size':number(collection_size,'collection size',1,10000,True),
                             'include':'curated unretrieved relevant examples and hard negatives; complete independent labels'},
            'repeated_pages':repeats,'expected_core_runs':count*len(conditions),'expected_repeat_runs':repeats*len(conditions),
            'budget_group':group,'stages':stages,'metadata_digest':digest(metadata),
            'roles':{'fixed_worker_ids':fixed,'dynamic_worker_ids':list(worker_ids),'capture_verifier_id':capture_verifier_id,
                     'structured_selector_id':fixed_workers[0]['id'],'decision_model_id':decision['id']}}
    result['digest']=digest(result)
    return result


def choose_pages(page_ids, count, seed):
    pages=sorted(set(page_ids))
    if len(pages)!=len(page_ids):raise ContractError('Frozen page IDs must be distinct')
    if len(pages)<count:raise ContractError('Insufficient acquired pages; record the partial pilot before changing its plan')
    return random.Random(str(seed)).sample(pages,count)


def resolve(recipe, stage, *, corpus_id, page_ids=None, list_id=None, oracle_ids=None, policy_id=None):
    """Produce a validated draft only. The normal catalogue/launch gates remain required."""
    entry=recipe['stages'][stage]
    if not entry['manifest']:raise ContractError('Connection probes require the typed provider adapter and a separately approved probe manifest')
    result=copy.deepcopy(entry['manifest']);result['corpus_id']=corpus_id
    if stage=='connection':
        result['source']={'kind':'urls','urls':['https://example.com/']}
    elif stage=='acquisition':
        if not list_id or list_id=='latest':raise ContractError('Select an identified pinned Tranco list')
        result['source']['list_id']=list_id
    else:
        pages=page_ids or []
        expected=recipe['sampling']['count']
        if stage in ('repeat','frozen-check'):expected=recipe['repeated_pages']
        if stage.startswith('retrieval-') or stage=='rag-effect':expected=recipe['rag_benchmark']['queries']
        result['source']={'kind':'snapshots','page_ids':choose_pages(pages,expected,recipe['seed'])}
    if stage=='rag-effect':
        if len(oracle_ids or [])!=recipe['rag_benchmark']['queries']:raise ContractError('Each planned query needs its adjudicated relevance reference')
        result['oracle_benchmark_ids']=oracle_ids
    if stage=='frozen-check':
        if not policy_id:raise ContractError('Freeze a verified learned policy first')
        result['policy_id']=policy_id
    return validate_manifest(result)
