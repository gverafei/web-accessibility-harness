"""Resumable campaign worker. No acquisition or provider activity occurs on import."""
import base64
import copy
import json
import random
import time
import uuid
from urllib.parse import urlsplit
from .contracts import ContractError, MeasurementIncomplete, canonical, digest, validate_manifest
from .controller import rule_level, distance, gate, materialize, preserved, profile, retain, worker_prompt, VERSION
from .environment import Environment
from .providers import Providers, BudgetStop, UncertainCall
from .retrieval import Retriever
from .sampling import sample
from .selection import select, reranker
from .technical import assess as technical_assessment, status as assessment_status, BASIS as EVALUATION_BASIS
from . import pausing
from .evidence_verifier import verify as verify_evidence
from .store import Conflict
from remediation_interventions import VERSION as CURRENT_INTERVENTIONS, PRESERVATION_VERSION, four_policy
from .capture_admission import assess as capture_assessment


def existing(store, ident):
    try: return store.get(ident)
    except KeyError: return None


def once(store, kind, data, campaign, ident):
    return existing(store,ident) or store.append(kind,data,campaign,ident)


def active_method(manifest):
    if manifest.get('acquisition_protocol'):
        raise ContractError('Acquisition-only campaigns use the verified acquisition adapter')
    if manifest.get('mode', 'frozen') != 'frozen' or manifest.get('policy_id'):
        raise ContractError('Learned policies are retired; create a new Decisions manifest')
    if manifest.get('experience_library_id') or manifest.get('record_experience'):
        raise ContractError('Cross-run remediation history is unavailable')
    from .worker_profile import validate
    if manifest.get('worker_profile_version'):
        validate(manifest['workers'])
    for condition in manifest['conditions']:
        if (condition.get('controls', {}).get('memory') or condition.get('selector') == 'linucb' or any(condition.get(k) for k in
                ('policy_id', 'guidance_policy_id', 'memory_policy_id'))):
            raise ContractError('Learned policies are retired; create a new Decisions manifest')


def create_campaign(store, value):
    manifest = validate_manifest(value)
    from .worker_profile import validate, VERSION as WORKER_PROFILE
    validate(manifest['workers'])
    decision=manifest.get('decision_model')
    if decision and decision['model']!='openai/gpt-6-luna-decisions':
        raise ContractError('Closed tasks use Decisions Luna.')
    manifest['worker_profile_version'] = WORKER_PROFILE
    active_method(manifest)
    campaign_id=uuid.uuid4().hex
    from .categories import category_vocabulary
    if not manifest['category_vocabulary']:
        if manifest['source']['kind']=='curated':
            manifest['category_vocabulary']=category_vocabulary([p['category'] for p in store.get(manifest['source']['curated_id'])['data']['candidates'] if p.get('category')])
        elif manifest['source']['kind']=='snapshots':
            manifest['category_vocabulary']=category_vocabulary([store.get(ident)['data']['profile']['category'] for ident in manifest['source']['page_ids'] if store.get(ident)['data']['profile'].get('category')])
    group = manifest.get('budget_group')
    if group:
        from .preparation import compatible_groups
        for row in store.list('campaign'):
            previous = row['data'].get('budget_group')
            if previous and previous['id'] == group['id'] and not compatible_groups(previous, group):
                raise ContractError('Shared budget group limits cannot change between campaigns')
    corpus = store.get(manifest['corpus_id'])
    if corpus['kind'] != 'corpus': raise ContractError('Select a frozen corpus snapshot')
    if manifest.get('rag_contrast'):
        groups = {}
        for c in manifest['conditions']:
            key = canonical({k:v for k,v in c.items() if k not in ('id','rag')})
            groups.setdefault(key,set()).add(c.get('rag','retrieved'))
        if any(v != {'off','retrieved','oracle'} for v in groups.values()): raise ContractError('RAG contrasts require matched off/retrieved/oracle conditions')
        if not manifest.get('oracle_benchmark_id') and not manifest.get('oracle_benchmark_ids'): raise ContractError('Choose the fully annotated relevance reference for the oracle condition')
    manifest['corpus_hash'] = corpus['hash']
    if manifest['source']['kind']=='curated':
        from .curated import select_source
        select_source(store,manifest['source'],manifest['partition'],manifest['seed'])
        manifest['source']['curated_hash']=store.get(manifest['source']['curated_id'])['hash']
    manifest['controller_version'] = VERSION
    from .versions import snapshot
    manifest['runtime_snapshot']=snapshot()
    manifest['digest'] = digest({k:v for k,v in manifest.items() if k!='digest'})
    row = store.append('campaign',manifest,ident=campaign_id)
    store.checkpoint(row['id'],{'status':'draft','stage':'configuration','next_page':0,'pages':[], 'runs':[]})
    return row


def launch(store, campaign_id):
    campaign = store.get(campaign_id)
    active_method(campaign['data'])
    if campaign['kind']!='campaign': raise ContractError('Unknown campaign')
    state,rev = store.checkpoint(campaign_id)
    if state.get('status') not in ('draft','blocked','interrupted','paused'): raise ContractError('Campaign is not launchable')
    from .providers import Ledger
    calls = Ledger(store).rows(campaign_id)
    if any(c['cost_status']=='unknown' or c['status']=='dispatching' for c in calls):
        raise UncertainCall('Resolve the recorded provider consumption before resuming')
    store.append('execution_authorization', {'campaign_id':campaign_id,'manifest_hash':campaign['hash'],
                  'source':campaign['data']['source'],'cost_limit':campaign['data']['campaign_cost_limit']}, campaign_id)
    store.checkpoint(campaign_id+'-pause',{'requested':False})
    state.update(status='queued',error=None)
    store.checkpoint(campaign_id,state,rev)


class Engine:
    def __init__(self, store, settings, environment=None, provider_factory=Providers, retriever_factory=Retriever):
        self.store, self.settings = store, settings
        self.environment = environment or Environment(store)
        self.provider_factory, self.retriever_factory = provider_factory,retriever_factory
        self.owner = uuid.uuid4().hex

    def persist(self, ident, state):
        self.store.checkpoint(ident,state)

    def frame(self, campaign):
        manifest, ident = campaign['data'],campaign['id']
        active_method(manifest)
        record = existing(self.store,ident+'-frame')
        if record: return record['data']['sample']
        source = manifest['source']
        if source['kind']=='curated':
            from .curated import select_source
            samples=select_source(self.store,source,manifest['partition'],manifest['seed'])
            data={'source':source,'sample':samples,'sampler':'curated-partition-v1'}
        elif source['kind']=='snapshots':
            samples=[]
            for i,page_id in enumerate(source['page_ids']):
                page=self.store.get(page_id)
                if page['kind']!='page': raise ContractError('Invalid frozen page ID')
                url=page['data']['source']['url'];samples.append({'url':url,'domain':urlsplit(url).hostname,'order':i,'role':'selected','page_id':page_id})
            data={'source':source,'sample':samples,'sampler':'reused-frozen-page-v1'}
        elif source['kind']=='urls':
            samples = [{'url':url,'role':'selected','order':i,'domain':urlsplit(url).hostname} for i,url in enumerate(source['urls'])]
            data = {'source':source,'sample':samples,'sampler':'explicit-urls-v1'}
        else:
            from tranco_sampling import fetch_latest_standard_list, fetch_pinned_standard_list, parse_tranco
            if source['list_id']=='latest': raw,filename,list_id = fetch_latest_standard_list()
            else:
                list_id = source['list_id']; raw,filename = fetch_pinned_standard_list(list_id)
            ranking,metadata = parse_tranco(raw,filename)
            blob = self.store.blob(raw,'tranco_frame',ident,'text/csv')
            samples = sample(ranking,list_id,manifest['seed'],source['count'],source['reserve_count'])
            data = {'list_id':list_id,'frame_id':blob['id'],'metadata':metadata,'sample':samples,'sampler':'whole-frame-srs-v1'}
        self.store.append('sampling_frame',data,ident,ident+'-frame')
        return samples

    def acquire(self, campaign, item, replaces=None):
        cid,manifest = campaign['id'],campaign['data']
        page_id = digest({'campaign':cid,'order':item['order']})[:32]
        pausing.check(self.store,cid)
        completed = existing(self.store,page_id)
        if completed: return completed
        if existing(self.store,page_id+'-failure'): return None
        try:
            self.store.assign_domain(manifest['study_id'],item['domain'].removeprefix('www.'),manifest['partition'])
            if item.get('page_id'):
                old=self.store.get(item['page_id'])
                self.admit_capture(self.store.get(old['data']['capture_id']),cid,page_id)
                if hasattr(self.environment,'verify_runtime'):
                    from .environment import EnvironmentChanged
                    previous=existing(self.store,old['campaign']+'-evaluator-runtime')
                    current=self.store.get(cid+'-evaluator-runtime')
                    if not previous or previous['data']!=current['data']:
                        raise EnvironmentChanged('Frozen baseline uses different or missing evaluator versions; acquire a new comparable baseline')
                if hasattr(self.environment,'replay_check'):
                    if not old['data'].get('replay_admission_id'):raise ContractError('Frozen page requires current replay admission')
                    if self.store.get(old['data']['replay_admission_id'])['data']['status']!='admitted':raise ContractError('Frozen reproduction has not been admitted')
                self.store.assign_domain(manifest['study_id'],'snapshot:'+self.store.get(old['data']['original_id'])['data']['sha256'],manifest['partition'])
                return self.store.append('page',old['data'] | {'source':item,'parent_page_id':old['id'],'partition':manifest['partition']},cid,page_id)
            capture = existing(self.store,page_id+'-capture') or self.environment.capture(item['url'],cid,page_id+'-capture')
            self.admit_capture(capture,cid,page_id)
            source_id=capture['data'].get('replay_source_id',capture['data']['rendered_id'])
            source = self.store.read_blob(source_id).decode()
            self.store.assign_domain(manifest['study_id'],urlsplit(capture['data']['captured_url']).hostname.removeprefix('www.'),manifest['partition'])
            self.store.assign_domain(manifest['study_id'],'snapshot:'+self.store.get(capture['data']['rendered_id'])['data']['sha256'],manifest['partition'])
            audit = existing(self.store,page_id+'-baseline') or self.environment.audit(capture,source,cid,page_id+'-baseline',manifest['evaluator'])
            if audit['data']['status'] != 'completed': raise ContractError('Baseline evaluation failed: '+str(audit['data'].get('error')))
            replay_id=None
            if hasattr(self.environment,'replay_check'):
                check=self.environment.replay_check(capture,source,cid,page_id+'-replay-admission',audit)
                verifier=verify_evidence(self.store,self.provider_factory(self.store,manifest,cid,self.settings),page_id+'-admission',page_id+'-evidence-verifier',capture,audit,check,manifest.get('capture_verifier'))
                replay_id=verifier['id']
                if verifier['data']['status']!='admitted':raise ContractError('Local reproduction '+verifier['data']['status']+': '+verifier['data']['rationale'])
            measured = audit['data']
            context = profile(source,measured,item['url']) | {'category':item.get('category') or 'unknown','category_source':item.get('category_source') or 'not supplied'}
            return self.store.append('page',{'source':item,'replaces':replaces,'capture_id':capture['id'],
                    'original_id':source_id,'audit_id':audit['id'],'profile':context,
                    'partition':manifest['partition'],'replay_admission_id':replay_id},cid,page_id)
        except pausing.PauseRequested:raise
        except (ContractError, ValueError, OSError, KeyError) as error:
            from .providers import BudgetStop
            if isinstance(error,UncertainCall):raise
            once(self.store,'acquisition_failure',{'source':item,'replaces':replaces,'error':str(error),'page_id':page_id},cid,page_id+'-failure')
            return None
        # Transport errors are persisted by execute(), not relabeled as observations.

    def admit_capture(self,capture,campaign,page_id):
        source=self.store.read_blob(capture['data']['rendered_id']).decode()
        result=once(self.store,'capture_admission',capture_assessment(source,capture['data'])|
                    {'capture_id':capture['id'],'source_id':capture['data']['rendered_id']},campaign,page_id+'-admission')
        if result['data']['status']=='failed':
            raise ContractError('Captured page is an access block or HTTP error: '+', '.join(result['data']['reasons']))

    def oracle(self, manifest, profile):
        from .benchmark import oracle_ids
        references=manifest.get('oracle_benchmark_ids') or [manifest['oracle_benchmark_id']]
        for reference in references:
            try:return oracle_ids(self.store,reference,profile)
            except ContractError:continue
        raise ContractError('No adjudicated oracle reference matches this frozen page and defect context')

    def retrieve(self, providers, manifest, condition, run_id, iteration, current_profile, audit):
        trace_id = f'{run_id}-rag-{iteration}'
        saved = existing(self.store,trace_id)
        retriever = self.retriever_factory(self.store,manifest['corpus_id'])
        if saved:
            examples = [retriever.by_id[i] for i in saved['data']['injected']]
            return examples,saved
        from .retrieval import measured_concepts
        defects = measured_concepts(audit)
        query = canonical({'purpose':current_profile['purpose'],'context':current_profile['repair_context'],
                           'failures':audit.get('failures',[]),
                           'lighthouse_failures':audit.get('lighthouse_failures',[])})
        mode = condition.get('rag','retrieved')
        if mode == 'off': examples,trace = [], {'query':query,'corpus_id':manifest['corpus_id'],'method':'explicit-off-ablation','injected':[], 'retrieved':[], 'candidates':[]}
        else:
            method=condition.get('retriever',manifest['retriever'])
            ranker = reranker(providers,run_id,trace_id+':rerank',current_profile) if method=='decisions' else None
            oracle = self.oracle(manifest,current_profile) if mode=='oracle' else None
            examples,trace = retriever.retrieve(query,defects,manifest['top_k'],method,ranker,oracle)
        return examples,self.store.append('retrieval',trace | {'run_id':run_id,'iteration':iteration,'condition':mode},providers.campaign,trace_id)

    def evidence(self, page, candidate, audit):
        original = self.store.read_blob(page['data']['original_id']).decode()
        original_audit = self.store.get(page['data']['audit_id'])['data']
        evidence = {page['data']['original_id']:{'role':'original acquired DOM','html':original},
                    candidate['source_id']:{'role':'candidate DOM','html':self.store.read_blob(candidate['source_id']).decode()},
                    audit['id']:{'role':'candidate audit','axe':audit['data']['axe'],'lighthouse':audit['data']['lighthouse'],
                                 'failures':audit['data']['failures'],'syntax':audit['data']['syntax'],
                                 'limitations':audit['data']['replay']},
                    page['data']['audit_id']:{'role':'original audit','axe':original_audit['axe'],
                                            'lighthouse':original_audit['lighthouse'],'failures':original_audit['failures']}}
        if candidate['source_id']==page['data']['original_id']:
            evidence[candidate['source_id']]['role']='original and candidate DOM: identical frozen artifact'
        if audit['id']==page['data']['audit_id']:
            evidence[audit['id']].update(role='original and candidate audit: unchanged page',syntax=audit['data']['syntax'],limitations=audit['data']['replay'])
        return evidence, []

    def run(self, campaign, page, condition, repetition):
        manifest,cid = campaign['data'],campaign['id']; self.active_campaign=cid
        from .prompt_policy import shared_strategy_prompt
        shared_prompt = shared_strategy_prompt(manifest)
        active_method(manifest)
        run_id = digest({'campaign':cid,'page':page['id'],'condition':condition['id'],'repetition':repetition})[:32]
        pausing.check(self.store,cid)
        if not self.store.claim(cid,self.owner,900): raise Conflict('Campaign is owned by another worker')
        if existing(self.store,run_id+'-result'):
            state,_=self.store.checkpoint(run_id)
            if state.get('status')=='completed': return run_id
            providers=self.provider_factory(self.store,manifest,cid,self.settings)
            state['status']='completed';self.persist(run_id,state)
            return run_id
        providers = self.provider_factory(self.store,manifest,cid,self.settings)
        original = self.store.read_blob(page['data']['original_id']).decode()
        from .html_tools import document_base_url
        from remediation_selection import rollback_feedback
        source_url=document_base_url(original,self.store.get(page['data']['capture_id'])['data'].get('captured_url') or page['data']['source']['url'])
        baseline = self.store.get(page['data']['audit_id'])
        state,_ = self.store.checkpoint(run_id)
        if not state:
            policy_id = None
            d = distance(baseline['data']['axe'],baseline['data']['lighthouse'],manifest['targets'])
            incumbent = {'source_id':page['data']['original_id'],'audit_id':baseline['id'],'distance':d,
                         'admissible':True,'technical':'passed','case_id':None,'original':True}
            state = {'status':'running','iteration':0,'stagnant':0,'incumbent':incumbent,'branch':None,
                     'policy_id':policy_id,'started':time.time(),'attempts':[]}
            self.persist(run_id,state)
            once(self.store,'run',{'page_id':page['id'],'condition_id':condition['id'],'repetition':repetition,
                       'policy_id':policy_id,'partition':manifest['partition'],'arm':condition.get('arm','standard')},cid,run_id)
        controls = condition.get('controls',{})
        current=manifest.get('intervention_version')==CURRENT_INTERVENTIONS
        zero_shot=condition['id']=='zero-shot'
        contextual_dynamic = current and condition['level'] == 6 and not zero_shot
        if zero_shot:
            condition=dict(condition,rag='off',selector='fixed')
        maximum=1 if zero_shot else manifest['max_iterations']
        providers.repair_deadline=state['started']+manifest['repair_budget']['max_seconds']
        providers.lease_owner=self.owner
        from accessibility_taxonomy.assessment import measure_pair
        taxonomy_capture=self.store.get(page['data']['capture_id'])
        taxonomy_origin=taxonomy_capture['data'].get('captured_url') or page['data']['source']['url']
        if manifest.get('decision_model'):
            # Measure the admitted original before any generation. This record
            # stays outside selector/generator feedback and shares document cache.
            baseline_id=run_id+'-taxonomy-baseline'
            premeasurement=existing(self.store,baseline_id)
            if not premeasurement:
                premeasurement=once(self.store,'taxonomy_baseline',{'run_id':run_id,
                    'phase':'before_generation','measurement':measure_pair(self.store,providers,run_id,
                        baseline,baseline,taxonomy_origin,manifest['decision_model'],taxonomy_capture)},cid,baseline_id)
            if premeasurement['data']['measurement'].get('status')!='completed':
                raise ContractError('Baseline taxonomy measurement failed before generation: '+
                    str(premeasurement['data']['measurement'].get('errors',[])))
        while state['iteration'] < maximum:
            from accessibility_taxonomy.consistency import pending, STOP_REASON
            if contextual_dynamic and pending(state):
                state['stop_reason'] = STOP_REASON
                break
            providers.completion_stage = None
            if state.get('empty_patch_count', 0) >= 2:
                state['stop_reason'] = 'Two proposals made no effective edit'
                break
            if not self.store.claim(cid,self.owner,900): raise Conflict('Campaign lease was lost')
            i = state['iteration']
            refine_original=(current and state['incumbent']['original'] and state['branch'] and state['stagnant']<2)
            if current and not zero_shot and not contextual_dynamic and i>0 and state.get('last_candidate_report') and manifest.get('decision_model'):
                from .refinement_decisions import choose
                review=choose(self.store,providers,run_id,run_id+'-refinement-'+str(i),manifest['decision_model'],state['last_candidate_report'])
                state['refinement_decision_id']=review['id']
                if review['data']['action']=='stop':state['stop_reason']='contextual refinement decision chose stop';break
                refine_original=(state['incumbent']['original'] or review['data']['action']=='repair_known_destinations')
            if i>0 and state['incumbent']['distance']==0 and state['incumbent']['technical']=='passed' and not refine_original and not zero_shot and not contextual_dynamic:break
            if time.time()-state['started'] >= manifest['repair_budget']['max_seconds']: state['stop_reason']='time limit'; break
            providers.begin_completion_stage('iteration', run_id)
            parent = state['branch'] or state['incumbent']
            audit = self.store.get(parent['audit_id'])
            parent_source = self.store.read_blob(parent['source_id']).decode()
            context = profile(parent_source,audit['data'],source_url) | {k:page['data']['profile'].get(k,'unknown') for k in ('category','category_source')}
            rows = providers.ledger.rows(cid,run_id,'repair')
            spent = sum(r['cost'] if r['cost'] is not None else r['reserved'] for r in rows)
            selection_state = {'axe':audit['data']['axe'],'distance':parent['distance'],'iteration':i,
              'max_iterations':manifest['max_iterations'],'stagnant':state['stagnant'],
              'cost_remaining':max(0,1-spent/max(.000001,manifest['repair_budget']['max_cost_usd'])),
              'time_remaining':max(0,1-(time.time()-state['started'])/manifest['repair_budget']['max_seconds']),
              'initial_level':rule_level(page['data']['profile'])}
            if contextual_dynamic:
                from .dynamic_objectives import load_evidence
                contextual = load_evidence(self.store, providers, run_id, cid, baseline,
                    audit, taxonomy_origin, manifest['decision_model'], taxonomy_capture)
                selection_state.update(lighthouse=audit['data']['lighthouse'],
                    measured_feedback={**(state.get('last_candidate_report') or {}),
                        'remaining_taxonomy_failures': contextual['taxonomy_failed'],
                        'taxonomy_coverage': contextual['taxonomy_coverage'],
                        'contextual_findings': contextual})
            decision_id = f'{run_id}-decision-{i}'
            decision = existing(self.store,decision_id)
            policy = self.store.get(state['policy_id']) if state['policy_id'] else None
            try:
                # Grounding is acquired before the very first repair decision.
                examples,retrieval = self.retrieve(providers,manifest,condition,run_id,i,context,audit['data'])
                if (i>0 or not current) and state['incumbent']['distance']==0 and state['incumbent']['technical']=='passed' and not refine_original and not zero_shot and not contextual_dynamic:
                    once(self.store,'decision',{'run_id':run_id,'iteration':i,'retrieval_id':retrieval['id'],'profile':context,
                         'selector':'deterministic-target-stop','available':['stop'],'selected':'stop'},cid,decision_id)
                    state['stop_reason']='targets met; original or better retained candidate kept';break
                if not decision:
                    choice = select(providers,run_id,decision_id+':selector',manifest,condition,context,selection_state,policy,bool(state['branch']))
                    decision = self.store.append('decision',choice | {'run_id':run_id,'iteration':i,'retrieval_id':retrieval['id']},cid,decision_id)
                action = decision['data']['selected']
                if action=='stop': state['stop_reason']=decision['data'].get('stop_reason') or 'selector found no supported useful correction'; break
                level,worker_id = action.split(':',1); level=int(level[1:])
                if condition['level'] == 6:
                    from remediation_interventions import public_to_wire
                    if four_policy(manifest.get('intervention_version')):
                        level = public_to_wire(level)
                worker = next(w for w in manifest['workers'] if w['id']==worker_id)
                attempt_id = f'{run_id}-attempt-{i}'
                attempt = existing(self.store,attempt_id)
                if not attempt:
                    start = time.time()
                    guidance = ''
                    feedback = audit['data'] | {'rollback_feedback':state.get('rollback_feedback','')} if controls.get('feedback',True) else audit['data'] | {'failures':[],'patch_failures':[],'lighthouse_failures':[]}
                    refining=bool(state['branch']) and level>3 and state['branch'].get('worker_id',worker_id)==worker_id and state['branch'].get('assigned_level',level)==level
                    operation_level=2 if refining else level
                    if state['branch'] and not refining:
                        parent=state['incumbent'];audit=self.store.get(parent['audit_id']);parent_source=self.store.read_blob(parent['source_id']).decode()
                        feedback=audit['data'] | {'rollback_feedback':state.get('rollback_feedback','')}
                    if not shared_prompt:
                        feedback=feedback | {'decisions_repair_focus':decision['data'].get('repair_focus')}
                    patch_context = None
                    messages = []
                    if contextual_dynamic and not shared_prompt:
                        from .dynamic_objectives import (
                            corrective_messages, scoped_evidence_enabled, repair_work, work_messages)
                        contextual = load_evidence(self.store, providers, run_id, cid, baseline,
                            audit, taxonomy_origin, manifest['decision_model'], taxonomy_capture)
                        if scoped_evidence_enabled(manifest):
                            work = repair_work(contextual, audit['data'],
                                decision['data'].get('repair_stage'),
                                version=manifest['adaptive_evidence_version'], editable_source=parent_source)
                            messages = work_messages(work, 'repair-generator')
                        else:
                            messages = corrective_messages(contextual)
                        if manifest.get('adaptive_patch_context_version'):
                            from remediation_patch_context import repair_context as localized_context
                            patch_context = localized_context(parent_source,
                                feedback.get('patch_failures', feedback.get('failures', [])),
                                feedback.get('lighthouse_failures', []),
                                contextual_evidence=work['active_contextual_evidence'],
                                target_coverage=manifest['adaptive_patch_context_version'])
                    prompt = worker_prompt(original,parent_source,feedback,operation_level,source_url,context,Retriever.grounding(examples),guidance,intervention_version=manifest.get('intervention_version')if operation_level!=2 else None,fidelity_reference_only=manifest.get('intervention_version')==CURRENT_INTERVENTIONS and refining,patch_context=patch_context)
                    if messages:
                        prompt += '\n' + '\n'.join(message['content'] for message in messages)
                    destination_repairs=[]
                    if current and refining:
                        from .candidate_admission import check
                        from .destination_repairs import cases
                        invalid=check(parent_source,{'text':'local repair context'},source_url,original)['metrics']['unverified_destinations']
                        destination_repairs=cases(original,parent_source,source_url,invalid)
                        if destination_repairs:prompt+='\nFor these source-grounded destination corrections only, emit set_attribute with the exact selector, name=href and value=after. Preserve the current design; other task attributes remain protected.\n'+canonical(destination_repairs)
                    if zero_shot:
                        from remediation_baseline import baseline_prompt
                        prompt=baseline_prompt(original)
                    image_parts=[]
                    if not zero_shot and four_policy(manifest.get('intervention_version')) and operation_level>=3 and worker.get('vision'):
                        captured=self.store.get(page['data']['capture_id'])['data'];image_id=captured.get('screenshot_id')
                        if image_id:
                            image_parts=[{'type':'image_url','image_url':{'url':'data:'+self.store.get(image_id)['data']['media_type']+';base64,'+base64.b64encode(self.store.read_blob(image_id)).decode()}}]
                            prompt+=('\nThe attached original capture is a reference for purpose, subject and available imagery; choose a new polished accessible composition freely. Fidelity differences are reported separately.'if manifest.get('intervention_version')==CURRENT_INTERVENTIONS and level>=4 else'\nThe attached capture is the immutable original reference for hierarchy, ordering, grouping and proportions. It does not prove unseen behavior.')
                    if not zero_shot and four_policy(manifest.get('intervention_version')) and operation_level>=4 and not image_parts:
                        raise ContractError('Current regeneration requires the immutable original capture before generation')
                    output = providers.chat(run_id,'repair',attempt_id+':worker',worker,prompt,json_mode=not zero_shot and operation_level<=3,**({'image_parts':image_parts}if image_parts else {}))
                    from remediation_jobs import repair_context
                    if patch_context is None:
                        patch_context=repair_context(parent_source,feedback.get('patch_failures',feedback.get('failures',[])),feedback.get('lighthouse_failures',[]))if operation_level<=3 else None
                    if zero_shot:
                        from remediation_baseline import baseline_candidate
                        candidate_source,raw=baseline_candidate(output,original,source_url,retain_raw=True)
                        patch={'applied':[{'action':'zero_shot_output'}],'rejected':[],'baseline':raw}
                    else:
                        candidate_source,patch = materialize(parent_source,output,operation_level,source_url,original,intervention_version=manifest.get('intervention_version')if operation_level!=2 else None,patch_context=patch_context,destination_repairs=destination_repairs,validation_version=manifest.get('patch_validation_version'))
                    if operation_level<=3 and not patch.get('applied') and patch.get('rejected'):
                        raise ContractError('No executable operation survived the intervention guards')
                    from remediation_completion import unchanged_proposal, NOOP_FEEDBACK
                    if (not zero_shot and operation_level <= 3
                            and unchanged_proposal(parent_source, candidate_source, {
                                'applied': patch.get('applied'), 'skipped': patch.get('rejected', [])})):
                        record = once(self.store, 'proposal_noop', {
                            'run_id': run_id, 'iteration': i + 1, 'decision_id': decision_id,
                            'level': level, 'worker_id': worker_id,
                            'parent_source_id': parent['source_id'], 'parent_audit_id': parent['audit_id'],
                            'patch': patch, 'feedback': NOOP_FEEDBACK, 'evaluated': False,
                        }, cid, attempt_id + '-noop')
                        state.setdefault('unmeasured_proposals', []).append(record['id'])
                        state['empty_patch_count'] = state.get('empty_patch_count', 0) + 1
                        state['rollback_feedback'] = NOOP_FEEDBACK
                        state['iteration'] += 1
                        self.persist(run_id, state)
                        continue
                    state['empty_patch_count'] = 0
                    source_id = self.store.blob(candidate_source,'candidate_html',cid,'text/html')['id']
                    candidate_audit = existing(self.store,attempt_id+'-audit') or self.environment.audit(
                        self.store.get(page['data']['capture_id']),candidate_source,cid,attempt_id+'-audit',manifest['evaluator'])
                    verification=None;quality=None
                    candidate_local=manifest.get('intervention_version')==CURRENT_INTERVENTIONS
                    candidate_taxonomy=None
                    if candidate_local and not zero_shot:
                        candidate_taxonomy=measure_pair(self.store,providers,run_id,baseline,candidate_audit,taxonomy_origin,manifest.get('decision_model'),taxonomy_capture)
                        if candidate_taxonomy.get('status')!='completed':raise ContractError('Candidate taxonomy must finish before selection')
                    if hasattr(self.environment,'replay_check'):
                        capture=self.store.get(page['data']['capture_id'])
                        if candidate_local:
                            from .candidate_admission import evaluate
                            quality=evaluate(self.store,capture,candidate_audit,candidate_source,source_url,cid,attempt_id+'-candidate-usability',reference_source=original)
                        else:quality=self.environment.replay_check(capture,candidate_source,cid,attempt_id+'-replay-admission',candidate_audit)
                        verification=verify_evidence(self.store,providers,run_id,attempt_id+'-evidence-verifier',capture,candidate_audit,quality,manifest.get('capture_verifier'),candidate=True,structure_first=manifest.get('intervention_version')==PRESERVATION_VERSION,candidate_local=candidate_local,reference_source=original if candidate_local else None)
                        if candidate_local and verification['data'].get('response_contract_error'):
                            raise MeasurementIncomplete('Visual review response contract failed: '+verification['id'])
                    checks = preserved(original,candidate_source,source_url,structure_first=four_policy(manifest.get('intervention_version')),image_asset_equivalence=manifest.get('intervention_version')==CURRENT_INTERVENTIONS)
                    d = distance(candidate_audit['data']['axe'],candidate_audit['data']['lighthouse'],manifest['targets']) if candidate_audit['data']['status']=='completed' else parent['distance']
                    attempt = self.store.append('attempt',{'run_id':run_id,'page_id':page['id'],'iteration':i,'level':level,'operation_level':operation_level,'worker_id':worker_id,
                      'evidence_verification_id':verification['id'] if verification else None,'candidate_usability_id':quality['id']if candidate_local and quality else None,'worker_digest':worker['digest'],'source_id':source_id,'audit_id':candidate_audit['id'],'distance':d,
                      'preservation':checks,'patch':patch,'decision_id':decision['id'],'retrieval_id':retrieval['id'],
                      **({'candidate_taxonomy':candidate_taxonomy}if candidate_taxonomy is not None else{}),
                      'before':{'distance':parent['distance'],'preserved_success':parent['distance']==0 and parent['technical']=='passed'},
                      'seconds':time.time()-start},cid,attempt_id)
                data = attempt['data']; candidate_audit = self.store.get(data['audit_id'])
                if contextual_dynamic:
                    from accessibility_taxonomy.consistency import record, attach
                    review = record(self.store, cid, contextual.get('assessment_id'), data.get('candidate_taxonomy'))
                    attach(state, review)
                case_id = attempt_id+'-case'
                case = existing(self.store,case_id)
                if not case:
                    ev,_ = self.evidence(page,data,candidate_audit)
                    verification = self.store.get(data['evidence_verification_id'])['data'] if data.get('evidence_verification_id') else None
                    assessment = technical_assessment(candidate_audit['data'], data['preservation'], verification, self.store.get(page['data']['audit_id'])['data'],fidelity_required=manifest.get('intervention_version')!=CURRENT_INTERVENTIONS,usability=self.store.get(data['candidate_usability_id'])['data']if data.get('candidate_usability_id')else None)
                    case = self.store.append('technical_assessment',{'run_id':run_id,'page_id':page['id'],'attempt_id':attempt_id,
                             'evidence':ev,'assessment':assessment},cid,case_id)
                technical = assessment_status(case)
                candidate = {'source_id':data['source_id'],'audit_id':data['audit_id'],'distance':data['distance'],
                             'admissible':(not data.get('evidence_verification_id') or self.store.get(data['evidence_verification_id'])['data']['status']=='admitted') and (technical=='passed' if manifest.get('intervention_version')==CURRENT_INTERVENTIONS else gate(candidate_audit['data'],data['preservation'],controls.get('preservation',True),self.store.get(page['data']['audit_id'])['data']) and (technical=='passed' or not controls.get('preservation',True))),
                             'technical':technical,'case_id':case_id,'original':False,'assigned_level':level,'worker_id':worker_id}
                if manifest.get('intervention_version')==CURRENT_INTERVENTIONS:
                    from remediation_selection import improvement_evidence,admitted_improvement
                    current_audit=self.store.get(state['incumbent']['audit_id'])['data']
                    state['incumbent']['quality_rank']=(state['incumbent']['distance'],current_audit['axe'],-current_audit['lighthouse'])
                    candidate['quality_rank']=(candidate['distance'],candidate_audit['data']['axe'],-candidate_audit['data']['lighthouse'])
                    gains=improvement_evidence(baseline['data']['axe'],baseline['data']['lighthouse'],candidate_audit['data']['axe'],candidate_audit['data']['lighthouse'],data.get('candidate_taxonomy'))
                    changed=admitted_improvement(technical,candidate['quality_rank'],state['incumbent']['quality_rank'],zero_shot=zero_shot,improvement=gains,incumbent_original=state['incumbent']['original'])
                    if contextual_dynamic and technical == 'passed' and candidate['quality_rank'] == state['incumbent']['quality_rank']:
                        from .dynamic_objectives import prefer_contextual_candidate, corrective_evidence
                        incumbent_audit = self.store.get(state['incumbent']['audit_id'])
                        previous_context = load_evidence(self.store, providers, run_id, cid, baseline,
                            incumbent_audit, taxonomy_origin, manifest['decision_model'], taxonomy_capture)
                        candidate_context = corrective_evidence(self.store, data['candidate_taxonomy'])
                        def contextual_report(values):
                            return {'candidate': {'axe': current_audit['axe'], 'lighthouse': current_audit['lighthouse']},
                                    'remaining_taxonomy_failures': values['taxonomy_failed'],
                                    'taxonomy_coverage': values['taxonomy_coverage'],
                                    'unresolved_prior_finding_count': values['unresolved_prior_finding_count']}
                        previous_retention = (state['incumbent'].get('retention') or
                            dict.fromkeys(('text_percent', 'links_percent', 'images_percent'), 100))
                        changed = changed or prefer_contextual_candidate(contextual_report(candidate_context),
                            contextual_report(previous_context), data['preservation'].get('retention', {}), previous_retention)
                        candidate['retention'] = data['preservation'].get('retention', {})
                    candidate['improvement']=gains
                    selected=candidate if changed else state['incumbent']
                    from .destination_repairs import cases
                    usability=case['data']['assessment']['checks'].get('candidate_usability')or{}
                    from .candidate_repair_context import functional_evidence
                    state['last_candidate_report']={'original':{'axe':baseline['data']['axe'],'lighthouse':baseline['data']['lighthouse']},'candidate':{'axe':candidate_audit['data']['axe'],'lighthouse':candidate_audit['data']['lighthouse']},'candidate_audit_id':candidate_audit['id'],'improvement':gains,'functional_evidence':functional_evidence(candidate_audit,self.store.get(data['candidate_usability_id'])['data'])if data.get('candidate_usability_id')else None,'functional_status':usability.get('status'),'functional_reasons':usability.get('reasons',[]),'visual_status':(case['data']['assessment']['checks'].get('capture_verification')or{}).get('status'),'visual_impact':(case['data']['assessment']['checks'].get('capture_verification')or{}).get('impact'),'visual_blocking_confidence':(case['data']['assessment']['checks'].get('capture_verification')or{}).get('blocking_confidence'),'visual_warnings':(case['data']['assessment']['checks'].get('capture_verification')or{}).get('warnings',[]),'destination_repairs':cases(original,self.store.read_blob(data['source_id']).decode(),source_url,usability.get('metrics',{}).get('unverified_destinations',[]))if level>=4 else[]}
                elif zero_shot:selected,changed=candidate,True
                else:selected,changed = retain(state['incumbent'],candidate,controls.get('retention',True))
                self.store.append('retention',{'run_id':run_id,'attempt_id':attempt_id,'previous':state['incumbent'],'candidate':candidate,
                                  'selected':selected,'changed':changed,'controls':controls},cid,attempt_id+'-retention') if not existing(self.store,attempt_id+'-retention') else None
                state['incumbent'] = selected
                state['rollback_feedback']='' if changed else rollback_feedback(
                    'Use the retained document and its measured findings; preserve acquired content and tasks.',
                    data.get('patch',{}).get('applied',[]),data['distance'],selected['distance'])
                evidence_ok=not data.get('evidence_verification_id') or self.store.get(data['evidence_verification_id'])['data']['status']=='admitted'
                if level>3: state['branch'] = candidate if evidence_ok and (technical=='passed' if manifest.get('intervention_version')==CURRENT_INTERVENTIONS else gate(candidate_audit['data'],data['preservation'])) else None
                elif state['branch'] and evidence_ok and gate(candidate_audit['data'],data['preservation']) and candidate['distance']<state['branch']['distance']:
                    state['branch'] = candidate
                state['stagnant'] = 0 if changed else state['stagnant']+1
                state['attempts'].append(attempt_id); state['iteration']+=1
                self.persist(run_id,state)
            except BudgetStop as error:
                state['stop_reason']=str(error); break
            except UncertainCall: raise
            except MeasurementIncomplete as error:
                once(self.store,'attempt_error',{'run_id':run_id,'iteration':i,'error':str(error),'instrument_error':True},cid,f'{run_id}-error-{i}')
                state.update(status='failed',stop_reason=str(error));self.persist(run_id,state)
                raise
            except (ContractError,ValueError,TypeError,KeyError) as error:
                once(self.store,'attempt_error',{'run_id':run_id,'iteration':i,'error':str(error)},cid,f'{run_id}-error-{i}')
                state['rollback_feedback']='The previous response was invalid or incomplete and was not adopted: '+str(error)[:1600]+'. Repair the retained document using its current findings.'
                state['stagnant']+=1;state['iteration']+=1
                state['stop_reason']='invalid or incomplete evidence';self.persist(run_id,state)
        retained = state['incumbent']; measured=self.store.get(retained['audit_id'])['data']
        if retained['original']:
            case_id=run_id+'-retained-case'
            case=existing(self.store,case_id)
            if not case:
                candidate={'source_id':retained['source_id']}
                ev,_=self.evidence(page,candidate,self.store.get(retained['audit_id']))
                assessment=technical_assessment(measured,{'status':'passed','scope':'Identical original content and controls'})
                case=self.store.append('technical_assessment',{'run_id':run_id,'page_id':page['id'],'attempt_id':None,
                   'evidence':ev,'assessment':assessment},cid,case_id)
            retained=retained | {'case_id':case_id,'technical':assessment_status(case)}
            state['incumbent']=retained
        taxonomy=measure_pair(self.store,providers,run_id,self.store.get(page['data']['audit_id']),
            self.store.get(retained['audit_id']),taxonomy_origin,manifest.get('decision_model'),taxonomy_capture)
        current=manifest.get('intervention_version')==CURRENT_INTERVENTIONS
        fidelity=preserved(original,self.store.read_blob(retained['source_id']).decode(),source_url,structure_first=four_policy(manifest.get('intervention_version')),image_asset_equivalence=manifest.get('intervention_version')==CURRENT_INTERVENTIONS) if current else None
        result = once(self.store,'run_result',{'run_id':run_id,'page_id':page['id'],'condition_id':condition['id'],'repetition':repetition,
                 'policy_id':state['policy_id'],'partition':manifest['partition'],'arm':condition.get('arm','standard'),
                 'taxonomy_measurement':taxonomy,'selected':retained,'attempts':state['attempts'],'preservation':retained['technical'],
                 'evaluation_basis':EVALUATION_BASIS,'semantic_preservation':'not_assessed',
                 'preserved_success':retained['distance']==0 and retained['technical']=='passed',
                 'axe':measured['axe'],'lighthouse':measured['lighthouse'],'distance':retained['distance'],
                 'unmeasured_proposals':state.get('unmeasured_proposals', []),
                 **({'measurement_consistency':state['evaluator_consistency_review']} if state.get('evaluator_consistency_review') else {}),
                 'seconds':time.time()-state['started'],'stop_reason':state.get('stop_reason','targets or iteration limit'),
                 **({'intervention_version':CURRENT_INTERVENTIONS,'source_fidelity':fidelity,'preservation':fidelity['status'],'candidate_usability':retained['technical'],'evaluation_basis':'observable-candidate-usability-v1','admissible_success':retained['distance']==0 and retained['technical']=='passed','preserved_success':retained['distance']==0 and retained['technical']=='passed' and fidelity['status']=='passed'}if current else{})},cid,run_id+'-result')
        state['status']='completed'; self.persist(run_id,state)
        return run_id

    def execute(self, campaign_id):
        if not self.store.claim(campaign_id,self.owner,900): return False
        campaign=self.store.get(campaign_id); state,_=self.store.checkpoint(campaign_id)
        try:
            if state.get('status') not in ('queued','running'): return False
            from .versions import snapshot
            active_method(campaign['data'])
            if campaign['data']['runtime_snapshot'] != snapshot(): raise ContractError('Campaign runtime/source version changed; review a new frozen manifest before execution')
            if campaign['data'].get('provider_probe'):
                from .probes import execute as execute_probes
                providers=self.provider_factory(self.store,campaign['data'],campaign_id,self.settings)
                results=execute_probes(self.store,campaign['data'],campaign_id,providers)
                state.update(status='completed',stage='analysis',pages=[],runs=[],contract_probes=results)
                self.persist(campaign_id,state);return True
            if hasattr(self.environment,'verify_runtime'): self.environment.verify_runtime(campaign_id)
            state.update(status='running',stage='acquisition'); self.persist(campaign_id,state)
            items=self.frame(campaign); selected=[i for i in items if i['role']=='selected']; reserves=iter(i for i in items if i['role']=='reserve')
            pages=[]
            for item in selected:
                if not self.store.claim(campaign_id,self.owner,900): raise Conflict('Campaign lease was lost')
                page=self.acquire(campaign,item)
                while page is None:
                    reserve=next(reserves,None)
                    if reserve is None: break
                    if not self.store.claim(campaign_id,self.owner,900): raise Conflict('Campaign lease was lost')
                    page=self.acquire(campaign,reserve,replaces=item['url'])
                if page: pages.append(page)
                state['pages']=[p['id'] for p in pages]; self.persist(campaign_id,state)
            if campaign['data'].get('capture_only'):
                # Acquired pages can be annotated before a subsequent snapshot-only paired study.
                manifest=campaign['data'];providers=self.provider_factory(self.store,manifest,campaign_id,self.settings)
                for page in pages:
                    audit=self.store.get(page['data']['audit_id'])
                    condition={'rag':'retrieved','retriever':manifest['retriever']}
                    _,trace=self.retrieve(providers,manifest,condition,page['id']+'-diagnosis',0,page['data']['profile'],audit['data'])
                    once(self.store,'decision',{'run_id':page['id']+'-diagnosis','profile':page['data']['profile'],'retrieval_id':trace['id'],
                          'selector':'baseline-diagnosis','selected':'capture-only','available':[]},campaign_id,page['id']+'-diagnosis-decision')
                state.update(status='completed',stage='diagnosis',pages=[p['id'] for p in pages],runs=[])
                self.persist(campaign_id,state);return True
            state['stage']='remediation'; self.persist(campaign_id,state)
            runs=[]
            for page in pages:
                for rep in range(campaign['data']['repetitions']):
                    conditions=copy.deepcopy(campaign['data']['conditions'])
                    random.Random(digest({'seed':campaign['data']['seed'],'page':page['id'],'rep':rep})).shuffle(conditions)
                    for condition in conditions:
                        run_id=self.run(campaign,page,condition,rep); runs.append(run_id)
                        state['runs']=runs; self.persist(campaign_id,state)
            state.update(status='completed',stage='analysis',pages=[p['id'] for p in pages],runs=runs)
            self.persist(campaign_id,state)
        except pausing.PauseRequested as error:
            state.update(status='paused',error=None);self.persist(campaign_id,state)
        except Exception as error:
            state.update(status='blocked' if isinstance(error,UncertainCall) else 'interrupted',error=str(error))
            self.persist(campaign_id,state)
            self.store.append('execution_error',{'error':str(error),'type':type(error).__name__},campaign_id)
        finally: self.store.release(campaign_id,self.owner)
        return True

    def tick(self):
        for campaign in self.store.list('campaign'):
            state,_=self.store.checkpoint(campaign['id'])
            if state.get('status') in ('queued','running') and self.execute(campaign['id']): return True
        return False
