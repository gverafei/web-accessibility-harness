"""Adapters for the restored SQL remediation loop; no second generation pipeline."""
import json
import hashlib
import time
from pathlib import Path
from remediation_output_budget import MAX_OUTPUT_TOKENS, FULL_DOCUMENT_OUTPUT_TOKENS
from remediation_interventions import four_policy, public_to_wire, wire_to_public
from .contracts import ContractError, MeasurementIncomplete, digest, model_snapshot
from .store import Store
from .engine import Engine, create_campaign, existing, once, active_method
from .environment import Environment
from .providers import Providers, BudgetStop, UncertainCall
from .controller import profile, distance, preserved, rule_level
from .selection import select
from .technical import assess, BASIS
from .evidence_verifier import verify
from .capture_admission import assess as admission

VERSION = 'sql-decisions-bridge-v10'


def scoped_workers(choices, selected_id, encoded=None):
    """Freeze an explicit experimental subset without editing the user's catalogue."""
    pool = [model_snapshot(c) for c in choices]
    if encoded is not None:
        try:
            ids = json.loads(encoded)
        except (TypeError, ValueError) as error:
            raise ContractError('Invalid experimental worker subset') from error
        known = {w['id'] for w in pool}
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(i, str) or i not in known for i in ids)
                or len(ids) != len(set(ids))):
            raise ContractError('Choose distinct enabled workers for this experiment')
        pool = [next(w for w in pool if w['id'] == i) for i in ids]
    if selected_id not in {w['id'] for w in pool}:
        raise ContractError('The selected worker must belong to the experimental subset')
    return pool


def options(store, include_groups=True):
    groups = {}
    for row in store.list('campaign') if include_groups else ():
        group = row['data'].get('budget_group')
        if group:
            groups[group['id']] = group
    from rag_corpus import read_json
    corpora=store.list('corpus')
    collection=read_json('corpus.json').get('collection')
    active=[row for row in corpora if row['data'].get('metadata',{}).get('collection')==collection] if collection else corpora
    return {'corpora': active[-1:], 'groups': list(groups.values())}


def configure(store, settings, source, choice, values, *, frozen_source_binding=None):
    """Freeze GUI choices before a run is queued; credentials never enter evidence."""
    from remediation_model_choices import model_choices
    from .decision_models import catalogue, capture_choices
    pool = scoped_workers(model_choices(settings), choice['id'], values.get('harness_worker_ids'))
    controls = options(store, include_groups=not values.get('harness_budget_json'))
    corpus_id = values.get('harness_corpus')
    corpus = next((c for c in controls['corpora'] if c['id'] == corpus_id), None)
    group_id=values.get('harness_budget_group')
    group = next((g for g in controls['groups'] if g['id']==group_id),None) if group_id else (controls['groups'][-1] if controls['groups'] else None)
    if values.get('harness_budget_json'):
        from .preparation import budget_group
        group = budget_group(json.loads(values['harness_budget_json']))
    if not corpus or not group:
        raise ContractError('Choose a frozen corpus and an approved shared budget')
    from remediation_interventions import VERSION as CURRENT_INTERVENTIONS, LEGACY_VERSION, PRESERVATION_VERSION, public_to_wire, validate_version, four_policy
    version=validate_version(values.get('intervention_version',CURRENT_INTERVENTIONS))
    public_level=int(values.get('preservation_level',0))+1
    level=public_to_wire(public_level)if four_policy(version) else public_level
    if values.get('harness_learning') == 'development' or values.get('harness_policy_id'):
        raise ContractError('Learned policies are retired; use Decisions without a policy')
    partition = values.get('harness_partition', 'development')
    if partition not in ('development', 'validation', 'test'):
        raise ContractError('Choose development, validation or test')
    policy_id = None
    selector = values.get('harness_selector', 'decisions')
    if selector != 'decisions':
        raise ContractError('The dynamic harness uses Decisions')
    verifier = next((w for w in capture_choices(settings) if w['id'] == values.get('harness_verifier') and w.get('vision')), None)
    if not verifier:
        raise ContractError('Choose an approved capture verification model')
    single = values.get('execution_mode') == 'single_shot'
    stage = 'remediation'
    group = dict(group, stage=stage)
    if stage not in group['stage_limits']:
        raise ContractError('The approved budget has no matching stage')
    category = source.get('site_category') or 'unknown'
    # Keep the category vocabulary consistent across development pages.
    categories = sorted({p.get('category') for c in store.list('curated_source')
                         for p in c['data'].get('candidates',[]) if p.get('category')})
    from classify_site_categories import CATEGORIES
    categories=sorted(set(categories)|set(CATEGORIES))
    if category != 'unknown' and category not in categories:
        categories.append(category)
    worker_id = choice['id']
    condition = {'id': 'zero-shot' if single else 'P'+str(level), 'level': level,
                 'worker_id': worker_id, 'selector': selector if level == 6 else 'fixed',
                 'controls': {'memory': False, 'guidance': not single}}
    amount = float(values['max_cost_usd']); seconds = int(values['max_execution_seconds'])
    from .contracts import number
    call_limit = number(values.get('harness_max_call_cost_usd', str(amount)), 'per-call cost budget', 0, amount)
    decisions = next((d for d in catalogue(settings) if d['enabled'] and d['is_default']), None)
    study_id = values.get('harness_study_id') or 'slider-development'
    manifest = {'name': values.get('title') or 'Slider remediation', 'study_id': study_id,
        'seed': str(source['id']), 'mode': 'frozen', 'partition':partition, 'policy_id':policy_id,
        'source': {'kind':'urls','urls':[source.get('captured_url') or source['url']]},
        'workers':pool,'capture_verifier':verifier,'category_review_model':decisions if not single else None,'conditions':[condition], 'repetitions':1,
        'max_iterations':1 if single else int(values['max_iterations']),
        'time_policy':'finish-started-iteration-and-taxonomy-v1',
        'repair_budget':{'max_cost_usd':amount,'max_seconds':seconds,'max_calls':1 if single else 24,'max_output_tokens':FULL_DOCUMENT_OUTPUT_TOKENS,'max_call_cost_usd':call_limit},
        'review_budget':{'max_cost_usd':amount,'max_seconds':seconds,'max_calls':200,'max_output_tokens':1500,'max_call_cost_usd':call_limit},
        'campaign_cost_limit':amount, 'targets':{'max_axe':int(values['max_axe']), 'min_lighthouse':int(values['min_lighthouse'])},
        'corpus_id':corpus_id, 'retriever':'mapped','top_k':int(values.get('rag_top_k',4)),
        'category_vocabulary':sorted(set(categories)),'decision_model':decisions,
        'orchestrator':model_snapshot(choice) if level==6 and selector=='structured' else None,
        'budget_group':group}
    from accessibility_taxonomy.contextual_judge import default_configuration, MIN_OUTPUT_TOKENS
    manifest.update(default_configuration(settings, decisions))
    manifest['review_budget']['max_output_tokens'] = MIN_OUTPUT_TOKENS
    if values.get('stop_at_perfect_audit') in ('1', 'on', True):
        manifest['stop_at_perfect_audit'] = True
    if four_policy(version):
        manifest['record_experience'] = False
        manifest['diagnosis_policy'] = 'disabled' if single else 'adaptive'
        manifest['intervention_version']=version
        manifest['native_control_state_required']=True
        manifest['source_repeatability_required']=True
        if not single:
            from coordinated_role_validation import VERSION as PATCH_VALIDATION_VERSION
            manifest['patch_validation_version'] = PATCH_VALIDATION_VERSION
            manifest['candidate_review_mode']='diagnostic-only'
            manifest['refinement_policy']='budget-only-progress'
            from .iteration_policy import VERSION as ITERATION_POLICY
            from .time_policy import CANDIDATE_BOUNDARY
            manifest['iteration_policy'] = ITERATION_POLICY
            manifest['time_policy'] = CANDIDATE_BOUNDARY
            manifest['max_generation_attempts_per_candidate'] = number(
                values.get('max_generation_attempts_per_candidate', 20),
                'Attempts per candidate', 1, 1000, True)
            if 'stop_at_perfect_audit' not in values:
                manifest['stop_at_perfect_audit'] = True
            if level == 6:
                from .prompt_policy import VERSION as PROMPT_POLICY
                manifest['worker_prompt_policy'] = PROMPT_POLICY
        condition['public_level']=public_level
        condition['id']='zero-shot' if single else 'P'+str(public_level)
    if values.get('harness_experience_library'):
        raise ContractError('Cross-run remediation history is unavailable')
    if frozen_source_binding is not None:
        if frozen_source_binding.get('sql_source_id') != source['id']:
            raise ContractError('Frozen source binding does not match the selected acquisition')
        manifest['frozen_source_binding'] = frozen_source_binding
    row = create_campaign(store,manifest)
    from urllib.parse import urlsplit
    store.assign_domain(row['data']['study_id'], urlsplit(manifest['source']['urls'][0]).hostname.lower().removeprefix('www.'), partition)
    store.checkpoint(row['id'],{'status':'externally_managed','stage':'remediation','runs':[], 'pages':[]})
    return {'version':VERSION,'intervention_version':version,'campaign_id':row['id'],'single_shot':single,
            'category':category,'category_source':source.get('site_category_source') or 'unclassified',
            'rag_enabled':not single and values.get('act_grounding','on')!='off',
            'sql_source_id':source['id']}


class Bridge:
    def __init__(self, config, run, settings, store=None, environment=None, providers=None):
        self.config, self.sql_run, self.settings = config, run, settings
        self.store = store or Store()
        self.campaign = self.store.get(config['campaign_id'])
        self.cid=self.campaign['id']
        self.rid='sql-run-'+str(run['id'])
        from .versions import snapshot
        from .execution_recovery import resolve_manifest
        self.manifest, self.execution_revision = resolve_manifest(
            self.store, self.campaign, config.get('execution_revision_id'), snapshot(), self.rid)
        active_method(self.manifest)
        self.condition=self.manifest['conditions'][0]
        self.environment=environment or Environment(self.store)
        self.environment.evaluator_revision_id = config.get('evaluator_revision_id')
        self.providers=providers or Providers(self.store,self.manifest,self.cid,settings)
        self.engine=Engine(self.store,settings,environment=self.environment)
        self.state=self.store.checkpoint(self.rid)[0]
        self.number=0; self.call_index=0; self.audit_record=None; self.verification=None

    def prepare(self, source, rendered, screenshot, source_file):
        from .source_recovery import recover
        def require_native_reference():
            if self.manifest.get('native_control_state_required'):
                reference=self.capture['data'].get('native_control_reference')
                if not isinstance(reference,dict)or reference.get('version')!='observed-native-control-state-v1' or not isinstance(reference.get('records'),list):
                    raise ContractError('Observed native control state is unavailable; refresh the acquisition before remediation. No state is inferred from screenshots.')
        from urllib.parse import urlsplit
        origin = self.sql_run.get('captured_url') or self.sql_run['source_url']
        # Split protection precedes freezing, verification and all provider calls.
        self.store.assign_domain(self.manifest['study_id'],urlsplit(origin).hostname.lower().removeprefix('www.'),self.manifest['partition'])
        from .source_binding import resolve
        bound=None
        if self.manifest.get('frozen_source_binding') is not None:
            bound=resolve(self.store,self.manifest['frozen_source_binding'],
                          self.config['sql_source_id'],self.environment.binding_runtime(self.cid))
        if bound:
            self.capture=bound['capture'];self.baseline=bound['baseline']
            require_native_reference()
            check=bound['check'];source=bound['source'];identity=bound['identity']
        else:
            identity='sql-source-'+digest({'source':source,'rendered':rendered,'screenshot':Path(screenshot).read_bytes().hex(),
                                        'runtime':self.manifest['runtime_snapshot']})[:32]
            self.capture=existing(self.store,identity+'-capture')
            if not self.capture:
                self.capture=self.environment.freeze_source('http://dataset-server:8080/remediations/'+str(self.sql_run['id'])+'/source-baseline.html',
                    self.sql_run.get('captured_url') or self.sql_run['source_url'],source,rendered,screenshot,self.cid,identity+'-capture')
            require_native_reference()
            if self.condition['level'] in (4,5):
                self.capture=self.environment.with_design_resources(self.capture,self.cid)
            self.baseline=existing(self.store,identity+'-audit') or self.environment.audit(self.capture,source,self.cid,identity+'-audit',self.manifest['evaluator'])
            if self.baseline['data'].get('status')!='completed':
                raise ContractError('Instrument reproduction failed: '+str(self.baseline['data'].get('error') or 'Audit incomplete; source remains recoverable'))
            check=existing(self.store,identity+'-replay') or self.environment.replay_check(self.capture,source,self.cid,identity+'-replay',self.baseline)
            from .source_recovery import recover
            self.capture,source,self.baseline,check=recover(self.store,self.environment,self.capture,source,self.baseline,check,self.cid,identity,self.manifest['evaluator'])
        if self.manifest.get('source_repeatability_required'):
            from .source_repeatability import verify as repeat_source
            repeated=repeat_source(self.store,self.environment,self.capture,source,self.baseline,self.cid,self.manifest['evaluator'])
            if repeated['data']['status']!='admitted':
                repeat_check=once(self.store,'replay_admission',{
                    **check['data'],'status':'rejected',
                    'reasons':list(dict.fromkeys(check['data'].get('reasons',[])+repeated['data']['reasons'])),
                    'repeatability_id':repeated['id']},self.cid,identity+'-repeatability-replay')
                self.capture,source,self.baseline,check=recover(self.store,self.environment,self.capture,source,self.baseline,repeat_check,self.cid,identity,self.manifest['evaluator'])
                repeated=repeat_source(self.store,self.environment,self.capture,source,self.baseline,self.cid,self.manifest['evaluator'])
                if repeated['data']['status']!='admitted':
                    raise ContractError('Frozen source measurements are not repeatable; evidence retained before inference')
            self.source_repeatability=repeated
            # Capture recovery changes the reference being verified. Never
            # reuse an earlier visual judgment under its original identifier.
            identity+='-repeatable-'+digest({'capture':self.capture['id'],'audit':self.baseline['id'],'proof':repeated['id']})[:16]
        visible=admission(source,self.capture['data'])
        if visible['status']!='passed':
            raise ContractError('Stored source is not an admitted user-facing page: '+str(visible['reasons']))
        verification=verify(self.store,self.providers,self.rid,identity+'-verification',self.capture,self.baseline,check,self.manifest['capture_verifier'])
        source_admission = None
        if self.execution_revision and self.execution_revision['data'].get('source_admission_id'):
            from .source_admission import validate
            source_admission = validate(self.store, self.campaign, self.rid,
                self.execution_revision['data']['source_admission_id'], verification['id'])
        if verification['data']['status']!='admitted' and not source_admission:
            recovered=recover(self.store,self.environment,self.capture,source,self.baseline,check,self.cid,identity,self.manifest['evaluator'],verification=verification)
            if recovered[0]['id']!=self.capture['id']:
                self.capture,source,self.baseline,check=recovered
                verification=verify(self.store,self.providers,self.rid,identity+'-rendered-context-verification',self.capture,self.baseline,check,self.manifest['capture_verifier'])
        if verification['data']['status']!='admitted' and not source_admission:
            raise ContractError('Capture/replay verification blocked repair: '+verification['data']['rationale'])
        category_model=self.manifest.get('category_review_model')
        category_record=None
        if category_model:
            from .category_review import review
            category_ident='category-source-'+digest({'sql_source_id':self.config['sql_source_id'],'source':source,'model':category_model})
            observation={'id':self.config['sql_source_id'],'url':self.sql_run.get('source_url') or self.capture['data']['captured_url'],
                'site_category':self.config['category'],'site_category_source':self.config['category_source']}
            category_record=review(self.store,self.providers,self.rid,category_ident,category_model,observation,source)
            self.config=dict(self.config,category=category_record['data']['category'],category_source=category_record['id'])
        self.original=source; self.url=self.capture['data']['captured_url']
        context=profile(source,self.baseline['data'],self.url) | {k:self.config[k] for k in ('category','category_source')}
        self.context=context
        self.page=once(self.store,'page',{'capture_id':self.capture['id'],'audit_id':self.baseline['id'],
            'original_id':self.capture['data']['replay_source_id'],'source':{'url':self.url,'sql_source_id':self.config['sql_source_id']},
            'profile':context,'partition':self.manifest['partition'],
            **({'source_admission_id':source_admission['id']} if source_admission else {}),
            'verification_id':verification['id'],'category_review_id':category_record['id'] if category_record else None},self.cid,self.rid+'-page')
        if not self.state:
            d = distance(self.baseline['data']['axe'], self.baseline['data']['lighthouse'], self.manifest['targets'])
            incumbent={'source_id':self.page['data']['original_id'],'audit_id':self.baseline['id'],'distance':d,'original':True,'admissible':True,'technical':'passed','case_id':None}
            self.state={'status':'running','started':time.time(),'iteration':0,'stagnant':0,'policy_id':None,'incumbent':incumbent,'attempts':[]}
            once(self.store,'run',{'page_id':self.page['id'],'condition_id':self.condition['id'],'partition':self.manifest['partition'],
                'repetition':0,'policy_id':self.state['policy_id'],'sql_run_id':self.sql_run['id']},self.cid,self.rid)
            self.persist()
        self.providers.repair_deadline=self.state['started']+self.manifest['repair_budget']['max_seconds']
        return self.baseline['data']['raw_result']

    def prepared_source(self, source_file):
        """Use exactly the admitted original for every worker and preservation check."""
        frozen = self.store.read_blob(self.page['data']['original_id'])
        if frozen != self.original.encode('utf-8'):
            raise ContractError('Admitted source artifact and worker input differ')
        Path(source_file).write_bytes(frozen)
        return self.original

    def persist(self):
        self.store.checkpoint(self.rid,self.state)

    def record_unchanged_proposal(self, parent_document, feedback, patch, rationale=""):
        """Keep paid evidence without inventing a second measurement or candidate."""
        parent = self.state.get('branch') if self.level >= 4 else None
        parent = parent or self.state['incumbent']
        if self.store.read_blob(parent['source_id']).decode() != parent_document:
            raise ContractError('Unchanged proposal does not match its measured parent')
        record = once(self.store, 'proposal_noop', {
            'run_id': self.rid, 'iteration': self.number,
            'level': self.level, 'worker_id': self.worker['id'],
            'decision_id': self.decision['id'], 'parent_source_id': parent['source_id'],
            'parent_audit_id': parent['audit_id'], 'feedback': feedback,
            'patch': patch, 'proposal_rationale': str(rationale)[:600], 'consumption': self.costs(),
            'evaluated': False, 'reason': 'unchanged_measured_document',
        }, self.cid, self.attempt_id + '-noop')
        from remediation_completion import NOOP_FEEDBACK
        return self._finish_unmeasured_proposal(record, feedback, NOOP_FEEDBACK)

    def _finish_unmeasured_proposal(self, record, feedback, model_feedback):
        ids = self.state.setdefault('unmeasured_proposals', [])
        if record['id'] not in ids:
            ids.append(record['id'])
            self.state['empty_patch_count'] = self.state.get('empty_patch_count', 0) + 1
        self.state['last_noop'] = {key: record['data'][key]
                                   for key in ('iteration', 'level', 'worker_id', 'proposal_rationale')}
        self.state['last_noop']['feedback'] = model_feedback
        self.state['iteration'] = self.number
        self.state['feedback'] = feedback
        if self.state.get('loop_context'):
            self.state['loop_context'].update(completed_iteration=self.number, feedback=feedback)
        self.persist()
        self.providers.completion_stage = None
        return record

    def record_invalid_proposal(self, feedback, response_path):
        """Count an inapplicable paid output without a page, audit, or regenerated response."""
        from .iteration_policy import counts_candidates
        if self.condition['level'] != 6 and not counts_candidates(self.manifest):
            return None
        record = once(self.store, 'proposal_invalid', {
            'run_id': self.rid, 'iteration': self.number, 'level': self.level,
            'worker_id': self.worker['id'], 'decision_id': self.decision['id'],
            'response_path': str(response_path), 'feedback': feedback,
            'proposal_rationale': 'Invalid or inapplicable output; measured incumbent unchanged.',
            'consumption': self.costs(), 'evaluated': False, 'reason': 'invalid_output',
        }, self.cid, self.attempt_id + '-invalid')
        return self._finish_unmeasured_proposal(record, feedback, feedback)

    def previously_measured_candidate(self, candidate):
        """Recognize exact outputs already measured under this execution segment."""
        attempts = self.state.get('attempts', [])
        revision = getattr(self, 'execution_revision', None)
        if revision:
            attempts = attempts[len(revision['data']['prior_attempt_ids']):]
        encoded = candidate.encode('utf-8')
        for ident in reversed(attempts):
            record = self.store.get(ident)
            attempt = record['data']
            if (record['kind'] != 'attempt' or record['campaign'] != self.cid
                    or attempt.get('run_id') != self.rid):
                raise ContractError('Repeated-output lookup requires this run recorded attempts')
            audit = self.store.get(attempt['audit_id'])['data']
            if (audit.get('status') == 'completed'
                    and self.store.read_blob(attempt['source_id']) == encoded):
                return {'attempt_id': ident, 'source_id': attempt['source_id'],
                        'audit_id': attempt['audit_id']}
        return None

    def record_repeated_proposal(self, candidate, measured, feedback, patch, rationale=''):
        """Retain the response and earlier measurement without another candidate."""
        if measured != self.previously_measured_candidate(candidate):
            raise ContractError('Repeated proposal must match its recorded complete measurement')
        parent = self.state.get('branch') if self.level >= 4 else None
        parent = parent or self.state['incumbent']
        record = once(self.store, 'proposal_noop', {
            'run_id': self.rid, 'iteration': self.number,
            'level': self.level, 'worker_id': self.worker['id'],
            'decision_id': self.decision['id'],
            'parent_source_id': parent['source_id'], 'parent_audit_id': parent['audit_id'],
            'reused_attempt_id': measured['attempt_id'],
            'reused_source_id': measured['source_id'], 'reused_audit_id': measured['audit_id'],
            'feedback': feedback, 'patch': patch,
            'proposal_rationale': str(rationale)[:600], 'consumption': self.costs(),
            'evaluated': False, 'reason': 'previously_measured_candidate',
        }, self.cid, self.attempt_id + '-noop')
        from remediation_completion import REPEATED_PROPOSAL_FEEDBACK
        return self._finish_unmeasured_proposal(record, feedback, REPEATED_PROPOSAL_FEEDBACK)

    def repeated_unchanged_documents(self):
        """Close a measured document plateau without another paid advisory.

        Audit ties alone are insufficient. Require three actual documents from
        the same fixed intervention, allowing the first proposal two corrections.
        """
        attempts = self.state.get('attempts', [])
        revision = getattr(self, 'execution_revision', None)
        if revision:
            # A corrected instrument must get a chance to act. Earlier no-op
            # documents remain recorded and still count toward the attempt cap.
            attempts = attempts[len(revision['data']['prior_attempt_ids']):]
        if len(attempts) < 3:
            return False
        records = [self.store.get(ident)['data'] for ident in attempts[-3:]]
        levels = {record.get('level') for record in records}
        from remediation_interventions import active_wires
        if len(levels) != 1 or not levels.issubset(set(active_wires(self.manifest))):
            return False
        documents = [self.store.read_blob(record['source_id']) for record in records]
        return bool(documents[0]) and all(document == documents[0] for document in documents[1:])

    def block_stalled_dynamic_action(self, reason):
        """Retire one measured no-op route while keeping other P5 routes available."""
        attempts = self.state.get('attempts', [])
        noop = self.state.get('last_noop')
        if not attempts and not noop:
            return
        last = (noop if noop and self.state.get('empty_patch_count')
                else self.store.get(attempts[-1])['data'])
        public_level = (wire_to_public(last['level'])
                        if four_policy(self.manifest.get('intervention_version'))
                        else last['level'])
        action = f"P{public_level}:{last['worker_id']}"
        blocked = self.state.setdefault('blocked_actions', [])
        if action not in blocked:
            blocked.append(action)
        self.state['empty_patch_count'] = 0
        self.state['last_stalled_action'] = {'action': action, 'reason': reason}
        self.persist()

    def dynamic_selection_feedback(self):
        """Bound measured evidence before it reaches the advisory selector."""
        report = self.state.get('last_candidate_report') or {}
        costs = self.costs()
        feedback = {
            'original': report.get('original'),
            'candidate': report.get('candidate'),
            'candidate_retained': report.get('retained'),
            'content_retention': report.get('content_retention'),
            'remaining_taxonomy_failures': report.get('remaining_taxonomy_failures'),
            'taxonomy_coverage': report.get('taxonomy_coverage'),
            'remaining_lighthouse_failures': (report.get('remaining_lighthouse_failures') or [])[:8],
            'functional_status': report.get('functional_status'),
            'functional_reasons': (report.get('functional_reasons') or [])[:8],
            'visual_status': report.get('visual_status'),
            'visual_impact': report.get('visual_impact'),
            'visual_warnings': (report.get('visual_warnings') or [])[:8],
            'destination_repairs_count': len(report.get('destination_repairs') or []),
            'recent_attempts': self.state.get('progress_history', [])[-3:],
            'last_stalled_action': self.state.get('last_stalled_action'),
            'unmeasured_proposal': (self.state.get('last_noop')
                                   if self.state.get('empty_patch_count') else None),
            'consumption': {key: costs[key] for key in ('cost_usd', 'input_tokens', 'output_tokens', 'known')},
        }
        current = self.state.get('current_contextual_evidence')
        if current:
            feedback.update(
                remaining_taxonomy_failures=current['taxonomy_failed'],
                taxonomy_coverage=current['taxonomy_coverage'],
                contextual_findings=current,
            )
        return feedback

    def prepare_dynamic_context(self):
        """Resolve the current document's cached findings before selecting a route."""
        audit = self.store.get(self.state['incumbent']['audit_id'])
        evidence = self.contextual_evidence_for(audit['id'])
        self.state['current_contextual_evidence'] = evidence
        self.state['incumbent_contextual_report'] = {
            'candidate': {key: audit['data'][key] for key in ('axe', 'lighthouse')},
            'remaining_taxonomy_failures': evidence['taxonomy_failed'],
            'taxonomy_coverage': evidence['taxonomy_coverage'],
            'unresolved_prior_finding_count': evidence['unresolved_prior_finding_count'],
        }
        self.persist()

    def contextual_evidence_for(self, audit_id):
        from .dynamic_objectives import load_evidence
        return load_evidence(self.store, self.providers, self.rid, self.cid,
            self.baseline, self.store.get(audit_id), self.url,
            self.manifest['decision_model'], self.capture)

    def begin_iteration(self, number):
        from .time_policy import ITERATION_BOUNDARY,CANDIDATE_BOUNDARY
        from .iteration_policy import counts_candidates, candidate_limit_reached, generation_limit_reached, correcting_proposal
        from .run_stop import requested, REASON
        sql_run = getattr(self, 'sql_run', {})
        if sql_run.get('id') is not None and requested(self.store, sql_run['id']):
            self.state['stop_reason_override'] = REASON
            self.persist()
            return None, None
        candidate_policy = counts_candidates(self.manifest)
        if candidate_limit_reached(self.manifest, self.state):
            self.state['stop_reason_override'] = 'Evaluated candidate limit reached'
            self.persist()
            return None, None
        if candidate_policy and generation_limit_reached(self.manifest, self.state, number):
            limit = self.manifest['max_generation_attempts_per_candidate']
            self.state['stop_reason_override'] = (
                f'Generation attempt limit reached: {limit} attempts without another evaluable candidate')
            self.persist()
            return None, None
        revision = getattr(self, 'execution_revision', None)
        first_recovered_iteration = bool(revision and number == revision['data']['completed_iteration'] + 1)
        if first_recovered_iteration:
            self.state['empty_patch_count'] = 0
        dynamic = getattr(self, 'condition', {}).get('level') == 6
        contextual_dynamic = dynamic and four_policy(self.manifest.get('intervention_version'))
        from accessibility_taxonomy.consistency import pending, STOP_REASON
        if contextual_dynamic and pending(self.state):
            self.state['stop_reason_override'] = STOP_REASON
            self.persist()
            return None, None
        if dynamic and self.state.get('stagnant', 0) >= 2 and self.state.get('attempts'):
            self.block_stalled_dynamic_action('two_measured_nonimprovements')
        if not candidate_policy and self.state.get('empty_patch_count', 0) >= 2:
            if dynamic:
                self.block_stalled_dynamic_action('two_empty_patches')
            else:
                self.state['stop_reason_override'] = 'Two patch proposals made no effective change after a corrective opportunity'
                self.persist()
                return None, None
        if self.manifest.get('attempt_limit') and number>self.manifest['attempt_limit']:
            self.state['stop_reason_override']='Practical repair attempt limit reached'
            self.persist()
            return None,None
        if not candidate_policy and self.repeated_unchanged_documents():
            if dynamic:
                self.block_stalled_dynamic_action('three_identical_documents')
            else:
                self.state['stop_reason_override'] = 'Three measured proposals produced identical HTML'
                self.persist()
                return None, None
        self.providers.completion_stage = None
        started_before_deadline = bool(first_recovered_iteration and any(
            call['id'] in revision['data'].get('prior_call_ids', [])
            and call['logical_key'].startswith(self.rid + '-attempt-' + str(number - 1) + ':call:')
            and call['created'] <= self.state['started'] + self.manifest['repair_budget']['max_seconds']
            for call in self.providers.ledger.rows(self.cid, self.rid)))
        if ((number > 1 or candidate_policy) and self.manifest.get('time_policy') in (ITERATION_BOUNDARY,CANDIDATE_BOUNDARY)
                and time.time()-self.state['started'] >= self.manifest['repair_budget']['max_seconds']
                and not started_before_deadline):
            if candidate_policy:
                self.state['stop_reason_override'] = 'Execution time limit reached'
                self.persist()
            return None, None
        self.providers.begin_completion_stage('iteration', self.rid)
        self.number=number; self.call_index=0
        if contextual_dynamic:
            self.prepare_dynamic_context()
        incumbent=self.state['incumbent']; audit=self.store.get(incumbent['audit_id'])['data']
        if (candidate_policy and self.manifest.get('stop_at_perfect_audit')
                and self.state.get('attempts') and not incumbent.get('original')
                and audit['axe'] == 0 and audit['lighthouse'] == 100):
            self.state['stop_reason_override'] = 'Perfect audit targets reached; final assessments follow'
            self.persist()
            return None, None
        context=profile(self.store.read_blob(incumbent['source_id']).decode(),audit,self.url) | {k:self.config[k] for k in ('category','category_source')}
        selection_state={'axe':audit['axe'],'distance':incumbent['distance'],'iteration':number-1,'max_iterations':self.manifest['max_iterations'],
            'stagnant':self.state['stagnant'],'continuation_potential':self.state.get('continuation_potential',False),
            'continuation_reasons':self.state.get('continuation_reasons',[]),'initial_level':rule_level(self.page['data']['profile']),
            'cost_remaining':max(0,1-self.costs()['cost_usd']/max(.000001,self.manifest['repair_budget']['max_cost_usd'])),
            'time_remaining':max(0,1-(time.time()-self.state['started'])/self.manifest['repair_budget']['max_seconds'])}
        if candidate_policy:
            selection_state.update(iteration=len(self.state.get('attempts', [])),
                                   generation_attempt=number, iteration_unit='evaluated candidates')
        if dynamic:
            workers = {worker['id']: worker for worker in self.manifest['workers']}
            used_high_routes = []
            for attempt in self.state.get('progress_history', []):
                worker = workers.get(attempt.get('worker_id'), {})
                if worker.get('reasoning_effort') not in ('high', 'xhigh', 'max'):
                    continue
                wire_level = attempt.get('wire_level')
                public_level = (wire_to_public(wire_level)
                                if four_policy(self.manifest.get('intervention_version'))
                                else wire_level)
                route = {'policy': f'P{public_level}', 'model': worker.get('model')}
                if route not in used_high_routes:
                    used_high_routes.append(route)
            selection_state.update(
                lighthouse=audit['lighthouse'],
                blocked_actions=list(self.state.get('blocked_actions', [])),
                used_high_routes=used_high_routes,
                measured_feedback=self.dynamic_selection_feedback(),
            )
        key=self.rid+'-decision-'+str(number-1)
        if first_recovered_iteration and getattr(self, 'config', {}).get('reopen_stopped_decision_id'):
            from .execution_recovery import reopened_decision_key
            key = reopened_decision_key(self.store, self.cid, self.rid, number - 1,
                                       revision, self.config['reopen_stopped_decision_id'])
        policy=self.store.get(self.state['policy_id']) if self.state['policy_id'] else None
        from remediation_interventions import VERSION as CURRENT_INTERVENTIONS
        progress_feedback=self.manifest.get('refinement_policy')=='budget-only-progress'
        bounded_feedback=self.manifest.get('refinement_policy') in ('bounded-feedback','budget-only-progress')
        if (progress_feedback and not dynamic and number>1 and not first_recovered_iteration
                and (not candidate_policy or self.state.get('attempts') and not correcting_proposal(self.state))):
            from .progress_continuation import choose
            review=self.perform('decision-specialist', lambda: choose(self.store,self.providers,self.rid,self.rid+'-progress-'+str(number-1),self.manifest['decision_model'],self.state.get('progress_history',[]),
                {'targets':self.manifest['targets'],'stop_at_perfect_audit':self.manifest.get('stop_at_perfect_audit', False),'attempt_limit':self.manifest.get('attempt_limit'),'iteration_reference':self.manifest['max_iterations'],'seconds_reference':self.manifest['repair_budget']['max_seconds'],'elapsed_seconds':time.time()-self.state['started'],
                 'spent_usd':self.costs()['cost_usd'],'run_limit_usd':self.manifest['campaign_cost_limit'],
                 'iteration':len(self.state.get('attempts', [])) if candidate_policy else number-1,
                 **({'iteration_unit':'evaluated candidates','candidate_limit':self.manifest['max_iterations'],
                     'generation_attempt':number-1} if candidate_policy else {})},self.state.get('last_candidate_report',{})),
                ('measured_trajectory', 'remaining_findings', 'budget'))
            self.state['progress_continuation_id']=review['id'];self.persist()
            if review['data']['action']=='stop':
                self.state['stop_reason_override'] = review['data']['reason']
                self.persist()
                return None,None
        if number>1 and not bounded_feedback and self.manifest.get('intervention_version')==CURRENT_INTERVENTIONS and self.state.get('last_candidate_report') and not self.config['single_shot'] and self.manifest.get('decision_model'):
            from .refinement_decisions import choose
            review=choose(self.store,self.providers,self.rid,self.rid+'-refinement-'+str(number-1),self.manifest['decision_model'],self.state.get('last_candidate_report',{}))
            self.state['refinement_action']=review['data']['action'];self.state['refinement_decision_id']=review['id'];self.persist()
            if review['data']['action']=='stop':
                self.decision=once(self.store,'decision',{'run_id':self.rid,'iteration':number-1,'selector':'refinement-decisions','selected':'stop','available':['stop'],'refinement_decision_id':review['id'],'profile':context},self.cid,key)
                return None,None
        report=self.state.get('last_candidate_report')or{}
        if dynamic and number>1 and report.get('retained'):
            from .progress_continuation import completed_objective
            from .dynamic_objectives import remaining_context
            if (completed_objective(report, self.manifest['targets'],
                                    allow_minor_visual=contextual_dynamic)
                    and not (contextual_dynamic and remaining_context(self.dynamic_selection_feedback()))):
                self.state['stop_reason_override']='Measured objectives met without remaining actionable findings'
                self.persist()
                return None,None
        pending_review_findings=bool(report.get('functional_reasons') or report.get('visual_impact')=='material')
        repairable_branch=(contextual_dynamic or progress_feedback or bounded_feedback and pending_review_findings or self.manifest.get('intervention_version')==CURRENT_INTERVENTIONS
                           and (self.state.get('refinement_action')=='repair_known_destinations' or
                                incumbent.get('original') and
                                (bool(self.state.get('branch'))and self.state['stagnant']<2 or
                                 self.state.get('refinement_action')=='continue_local_refinement')))
        if number>1 and incumbent['distance']==0 and incumbent['technical']=='passed' and not self.config['single_shot'] and not repairable_branch:
            self.decision=once(self.store,'decision',{'run_id':self.rid,'iteration':number-1,
                'selector':'deterministic-target-stop','available':['stop'],'selected':'stop',
                'profile':context,'policy_version':self.state['policy_id']},self.cid,key)
            return None,None
        recorded=existing(self.store,key)
        choice=recorded['data'] if recorded else select(self.providers,self.rid,key+':selector',self.manifest,
            self.condition,context,selection_state,policy)
        action=choice['selected']
        if action=='stop':
            self.decision=recorded or self.store.append('decision',choice|{'run_id':self.rid,'iteration':number-1},self.cid,key)
            self.state['stop_reason_override'] = choice.get('stop_reason') or 'No supported useful route remains within the recorded permissions and limits'
            self.persist()
            return None,None
        level,ident=action.split(':',1)
        self.worker=next(w for w in self.manifest['workers'] if w['id']==ident)
        self.level=(public_to_wire(int(level[1:]))
                    if dynamic and four_policy(self.manifest.get('intervention_version'))
                    else int(level[1:]))
        self.attempt_id=self.rid+'-attempt-'+str(number-1)
        # The global incumbent remains the rollback/reward baseline. A matching
        # regenerated branch owns its own measured refinement and RAG context.
        parent=incumbent;branch=self.state.get('branch')
        if self.level>=4 and branch and (branch['level'],branch['worker_id'])==(self.level,self.worker['id']):
            parent=branch
        if contextual_dynamic:
            self.generation_contextual_evidence = self.contextual_evidence_for(parent['audit_id'])
        audit=self.store.get(parent['audit_id'])['data']
        repair_context=profile(self.store.read_blob(parent['source_id']).decode(),audit,self.url) | {k:self.config[k] for k in ('category','category_source')}
        if not self.config['rag_enabled']:
            self.examples=[]; self.retrieval=once(self.store,'retrieval',{'query':'','method':'zero-shot' if self.config['single_shot'] else 'explicit-off',
                'injected':[],'retrieved':[],'candidates':[],'corpus_id':self.manifest['corpus_id'],'run_id':self.rid,'iteration':number-1},self.cid,self.rid+'-rag-'+str(number-1))
        else:
            self.examples,self.retrieval=self.engine.retrieve(self.providers,self.manifest,self.condition,self.rid,number-1,repair_context,audit)
        self.decision=recorded or self.store.append('decision',choice|{'run_id':self.rid,'iteration':number-1,
            'retrieval_id':self.retrieval['id'],'repair_parent_audit_id':parent['audit_id']},self.cid,key)
        from .dynamic_objectives import scoped_evidence_enabled, repair_work
        if contextual_dynamic and scoped_evidence_enabled(self.manifest):
            self.generation_work = repair_work(self.generation_contextual_evidence, audit,
                self.decision['data'].get('repair_stage'),
                version=self.manifest['adaptive_evidence_version'],
                editable_source=self.store.read_blob(parent['source_id']).decode())
        if self.level in (4,5):
            self.capture=self.environment.with_design_resources(self.capture,self.cid)
        self.before={'distance':incumbent['distance'],'preserved_success':incumbent['distance']==0 and incumbent['technical']=='passed'}
        self.attempt_started=time.time()
        return self.level,self.worker

    def bind(self, runtime):
        self.task_runtime = runtime
        from remediation_tool_registry import ToolContract
        for name,handler in (('retrieve_accessibility_evidence',self.retrieve),('evaluate_candidate',self.evaluate)):
            contract,_=runtime.tools._tools[name]
            runtime.tools._tools[name]=(ToolContract(name,VERSION,contract.description,contract.required_inputs,contract.output_type,contract.deterministic),handler)

    def perform(self, role, handler, input_keys=()):
        runtime = getattr(self, 'task_runtime', None)
        return runtime.perform(role, handler, input_keys) if runtime else handler()

    def paid_call_identity(self, completed=False):
        if completed:
            row = getattr(self.providers, 'last_call', None) or {}
            return row.get('id') if row.get('campaign') == self.cid and row.get('run') == self.rid else None
        key = self.attempt_id + ':call:' + str(self.call_index)
        row = next((row for row in self.providers.ledger.rows(self.cid, self.rid)
                    if row['logical_key'] == key), None)
        return row['id'] if row else None

    def resume_saved_diagnosis(self, document=None, axe=None):
        """Read owned advice receipts and ground any findings in the current document."""
        if not getattr(self, 'execution_revision', None):
            return None
        key = self.attempt_id + ':call:' + str(self.call_index)
        call = next((row for row in self.providers.ledger.rows(self.cid, self.rid)
                     if row['logical_key'] == key and row['status'] == 'received'
                     and row['cost_status'] not in ('unknown', 'estimated', 'reserved')), None)
        if not call or not call.get('response_id'):
            return None
        from .contracts import digest
        request = self.store.get(call['request_id'])['data']['request']
        if digest(request) != call['request_hash']:
            raise ContractError('Saved advisory request checksum differs')
        content = request['messages'][0]['content']
        prompt = content if isinstance(content, str) else content[0]['text']
        if not prompt.startswith('You are the accessibility diagnosis agent BEFORE localized patch generation.'):
            return None
        response = json.loads(self.store.read_blob(call['response_id']))
        choice = (response.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        raw = None
        findings = []
        if message.get('refusal') or choice.get('finish_reason') == 'content_filter':
            return None
        if choice.get('finish_reason') == 'length' and not message.get('content'):
            reason = 'Previously paid diagnosis has no completion text. No finding is reused and no model is called.'
        elif document is not None and isinstance(message.get('content'), str) and message['content'].strip():
            from remediation_diagnosis import grounded_diagnosis
            try:
                grounded = grounded_diagnosis(json.loads(message['content']), document, axe or [])
            except (ValueError, TypeError):
                return None
            raw = message['content']
            findings = grounded['findings']
            reason = 'Previously received advice grounded again in the current document; no new model call.'
        else:
            return None
        self.call_index += 1
        self._advisory_completion_exhausted = True
        once(self.store, 'advisory_receipt_reused' if raw is not None else 'advisory_output_unavailable', {'run_id':self.rid, 'call_id':call['id'],
             'request_id':call['request_id'], 'response_id':call['response_id'],
             'execution_revision_id':self.execution_revision['id'], 'findings':findings,
             'document_sha256':hashlib.sha256(document.encode()).hexdigest() if document is not None else None, 'reason':reason},
             self.cid, key + ('-advisory-reused' if raw is not None else '-advisory-unavailable'))
        return (raw, call['input_tokens'] or 0, call['output_tokens'] or 0,
                call['cost'] or 0, call['elapsed'] or 0, response.get('model') or self.worker['model'])

    def replay_output_limit(self, requested):
        """Keep the allowance of an existing paid call; new calls use the new limit."""
        key = self.attempt_id + ':call:' + str(self.call_index)
        saved = next((row for row in self.providers.ledger.rows(self.cid, self.rid)
                      if row['logical_key'] == key), None)
        if not saved:
            return requested
        body = self.store.get(saved['request_id'])['data']['request']
        return body.get('max_tokens', requested)

    def _worker_retry_permitted(self, failed_call, key):
        if not failed_call or not getattr(self, 'execution_revision', None):
            return False
        authorization = existing(self.store, 'call-retry-' + failed_call['id'])
        if (not authorization or authorization['kind'] != 'call_retry_authorization'
                or authorization['campaign'] != self.cid
                or authorization['data'].get('run') != self.rid
                or authorization['data'].get('request_hash') != failed_call['request_hash']
                or failed_call['cost_status'] != 'reconciled'
                or not self.providers.ledger.retryable_failure(failed_call)):
            return False
        # Dispatch validates the reconciliation and byte-identical request again.
        if key == failed_call['logical_key']:
            return True
        retried = next((row for row in self.providers.ledger.rows(self.cid, self.rid)
                        if row['logical_key'] == authorization['data']['retry_key']), None)
        if (not retried or retried['status'] != 'received'
                or retried['cost_status'] not in ('provider_reported', 'reconciled', 'local')
                or retried['request_hash'] != failed_call['request_hash']
                or not retried.get('response_id')):
            return False
        payload = json.loads(self.store.read_blob(retried['response_id']))
        choice = (payload.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        return (choice.get('finish_reason') == 'stop' and not message.get('refusal')
                and isinstance(message.get('content'), str) and bool(message['content'].strip()))

    def transport(self, body):
        from .prompt_policy import shared_strategy_prompt
        shared_prompt = shared_strategy_prompt(self.manifest)
        role = getattr(getattr(self, 'task_runtime', None), 'active_task_name', None)
        prior_failure = existing(self.store, self.rid + '-worker-output-failure')
        if prior_failure and not getattr(self, '_advisory_completion_exhausted', False):
            key = self.attempt_id + ':call:' + str(self.call_index)
            failed_call = next((row for row in self.providers.ledger.rows(self.cid, self.rid)
                                if row['id'] == prior_failure['data']['call_id']), None)
            diagnostic_replay = (role == 'repair-diagnostician'
                and prior_failure['data']['finish_reason'] == 'length'
                and not prior_failure['data']['refused']
                and failed_call and failed_call['logical_key'] == key)
            cached = next((row for row in self.providers.ledger.rows(self.cid, self.rid)
                           if row['logical_key'] == key and row['status'] == 'received'
                           and row['cost_status'] not in ('unknown', 'reserved', 'estimated')), None)
            successful_replay = False
            if cached and cached.get('response_id'):
                saved_response = json.loads(self.store.read_blob(cached['response_id']))
                saved_choice = (saved_response.get('choices') or [{}])[0]
                saved_message = saved_choice.get('message') or {}
                successful_replay = (saved_choice.get('finish_reason') not in ('length', 'content_filter')
                    and not saved_message.get('refusal')
                    and isinstance(saved_message.get('content'), str)
                    and bool(saved_message['content'].strip()))
            if (not diagnostic_replay and not successful_replay
                    and not self._worker_retry_permitted(failed_call, key)):
                raise ContractError('Checkpointed incomplete worker output; no automatic continuation')
        if body['model']!=self.worker['model']:
            raise ContractError('A restored agent attempted an unfrozen worker substitution')
        body=dict(body,provider={'allow_fallbacks':False,'require_parameters':True},stream=False)
        body['max_tokens']=min(body['max_tokens'],self.manifest['repair_budget']['max_output_tokens'])
        key=self.attempt_id+':call:'+str(self.call_index);self.call_index+=1
        failure_key = key + '-worker-output-failure'
        focus=getattr(self,'decision',{}).get('data',{}).get('repair_focus')
        if focus and not self.config['single_shot'] and not shared_prompt:
            body['messages']=[*body.get('messages',[]),{'role':'system','content':
                'Decisions advisory repair focus: '+focus+'. Ground repairs in the measured findings and retain protected content/controls. This does not override strategy, tools or limits.'}]
        from .iteration_policy import counts_candidates
        if counts_candidates(self.manifest) and not self.config['single_shot']:
            body['messages'] = [*body.get('messages', []), {'role':'system', 'content':
                'Only changed, evaluated candidates count toward the configured candidate limit. '
                'Invalid, empty and unchanged proposals do not count. Correct them using the current '
                'validation feedback while time and authorized money remain. No permission or budget '
                'can be expanded. This is generation attempt '+str(self.number)+'.'}]
        elif self.manifest.get('refinement_policy')=='budget-only-progress' and not self.config['single_shot']:
            body['messages']=[*body.get('messages',[]),{'role':'system','content':
                'The time reference is flexible within the frozen attempt cap and monetary limits. This is iteration '+str(self.number)+'. Continue the fixed intervention with concise repairs grounded in the latest measured feedback. Preserve valid work and correct regressions. Do not change the strategy or model. Empty decorative broken pixels may be removed only by the validated remove_decorative_image operation.'}]
        from remediation_interventions import VERSION as CURRENT_INTERVENTIONS
        if self.condition.get('level') == 6 and not self.config.get('single_shot') and not shared_prompt:
            from .dynamic_objectives import corrective_messages, work_messages
            work = getattr(self, 'generation_work', None)
            body['messages'] = [*body.get('messages', []),
                *(work_messages(work, role) if work is not None else
                  corrective_messages(getattr(self, 'generation_contextual_evidence', None)))]
        if self.manifest.get('intervention_version')==CURRENT_INTERVENTIONS and not self.config.get('single_shot') and self.number>1:
            from .candidate_repair_context import messages as candidate_repair_messages
            body['messages']=[*body.get('messages',[]),*candidate_repair_messages(self.state.get('last_candidate_report'))]
        from .source_bound_repair import CURRENT_VERSION as ROLE_BOUND_VERSION, component_output_format
        from .repair_style_evidence import VERSION as STYLE_EVIDENCE_VERSION
        if (self.manifest.get('adaptive_evidence_version') in (ROLE_BOUND_VERSION, STYLE_EVIDENCE_VERSION)
                and role == 'component-planner' and self.level == 3
                and 'response_format' in self.worker.get('supported_parameters', [])):
            body['response_format'] = component_output_format()
        response=self.providers.dispatch(self.rid,'repair',key,self.worker,body,
            self.settings['openrouter_base_url'].rstrip('/')+'/chat/completions',self.settings.get('openrouter_api_key'))
        dispatched = getattr(self.providers, 'last_call', None)
        row=next(c for c in self.providers.ledger.rows(self.cid,self.rid)
                 if (c['id']==dispatched['id'] if isinstance(dispatched, dict)
                     else c['logical_key']==key))
        choice = (response.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        content = message.get('content')
        if self.config.get('single_shot'):
            # The original provider response/usage is already durable. Length,
            # refusal and empty text are observations, never regeneration cues.
            return (content if isinstance(content, str) else message.get('refusal') or '',
                    row['input_tokens'] or 0, row['output_tokens'] or 0,
                    row['cost'] or 0, row['elapsed'] or 0, response['model'])
        if (choice.get('finish_reason') in ('length', 'content_filter') or message.get('refusal')
                or not isinstance(content, str) or not content.strip()):
            once(self.store, 'worker_output_failure', {'run_id': self.rid, 'call_id': row['id'],
                'response_id': row['response_id'], 'finish_reason': choice.get('finish_reason'),
                'refused': bool(message.get('refusal')), 'content_present': bool(content),
                'transport_version': VERSION}, self.cid, failure_key)
            once(self.store, 'worker_output_failure', {'run_id': self.rid, 'call_id': row['id'],
                'response_id': row['response_id'], 'finish_reason': choice.get('finish_reason'),
                'refused': bool(message.get('refusal')), 'content_present': bool(content),
                'transport_version': VERSION}, self.cid, self.rid + '-worker-output-failure')
            if role == 'repair-diagnostician' and choice.get('finish_reason') == 'length' and not message.get('refusal'):
                self._advisory_completion_exhausted = True
            from .contracts import ModelOutputIncomplete
            reason = 'refused' if message.get('refusal') else choice.get('finish_reason') or 'missing_text'
            raise ModelOutputIncomplete(reason, (row['input_tokens'] or 0, row['output_tokens'] or 0,
                row['cost'] or 0, row['elapsed'] or 0, response.get('model') or self.worker['model']),
                call_id=row['id'], response_id=row['response_id'])
        return content,row['input_tokens'] or 0,row['output_tokens'] or 0,row['cost'] or 0,row['elapsed'] or 0,response['model']

    def retrieve(self, **kwargs):
        return self.examples

    def worker_contextual_evidence(self):
        """Localize only this proposal's work; complete measurements stay in state."""
        from .prompt_policy import shared_strategy_prompt
        if shared_strategy_prompt(getattr(self, 'manifest', {})):
            return None
        work = getattr(self, 'generation_work', None)
        if work is not None:
            active = work['active_contextual_evidence']
            return active if active.get('failed_opportunities') or active.get('unresolved_prior_findings') else None
        return getattr(self, 'generation_contextual_evidence', None)

    def evaluate(self, request_payload):
        path=Path('/datasets/remediations')/str(self.sql_run['id'])/Path(request_payload['urls'][0]).name
        source=path.read_text()
        ident=self.attempt_id+'-audit'
        self.audit_record=existing(self.store,ident)
        if self.audit_record:
            from .loop_checkpoint import validate_audit_source
            validate_audit_source(self.audit_record, source, self.manifest.get('source_repeatability_required', False))
        else:
            self.audit_record=self.environment.audit(self.capture,source,self.cid,ident,self.manifest['evaluator'])
        from remediation_interventions import VERSION as CURRENT_INTERVENTIONS, PRESERVATION_VERSION, four_policy
        current=self.manifest.get('intervention_version')==CURRENT_INTERVENTIONS
        if current:
            from .candidate_admission import evaluate
            replay=evaluate(self.store,self.capture,self.audit_record,source,self.url,self.cid,self.attempt_id+'-candidate-usability',reference_source=self.original)
            self.candidate_taxonomy=None
            if not self.config['single_shot']:
                from accessibility_taxonomy.assessment import measure_pair
                self.candidate_taxonomy = self.perform('contextual-assessor', lambda:
                    measure_pair(self.store,self.providers,self.rid,self.baseline,
                        self.audit_record,self.url,self.manifest.get('decision_model'),self.capture),
                    ('candidate_audit', 'reference_audit', 'taxonomy'))
                if self.candidate_taxonomy.get('status')!='completed':
                    raise MeasurementIncomplete('Candidate taxonomy must finish before selection: '+ '; '.join(self.candidate_taxonomy.get('errors',[])))
                if self.condition.get('level') == 6:
                    from accessibility_taxonomy.consistency import record, attach
                    prior = (getattr(self, 'generation_contextual_evidence', None)
                             or self.state.get('current_contextual_evidence') or {})
                    review = record(self.store, self.cid, prior.get('assessment_id'), self.candidate_taxonomy)
                    attach(self.state, review)
        else:
            replay=self.environment.replay_check(self.capture,source,self.cid,self.attempt_id+'-replay',self.audit_record)
        self.verification = self.perform('visual-reviewer', lambda:
            verify(self.store,self.providers,self.rid,self.attempt_id+'-verification',self.capture,self.audit_record,replay,self.manifest['capture_verifier'],candidate=True,structure_first=self.manifest.get('intervention_version')==PRESERVATION_VERSION,candidate_local=current,reference_source=self.original if current else None),
            ('candidate_capture', 'candidate_audit', 'local_checks'))
        if (current and self.verification['data'].get('response_contract_error')
                and not self.config['single_shot']
                and self.manifest.get('candidate_review_mode', 'gate') != 'diagnostic-only'):
            raise MeasurementIncomplete('Visual review response contract failed; repair generation must not repeat to compensate for an instrument error. Evidence: '+self.verification['id'])
        self.preservation=preserved(self.original,source,self.url,structure_first=four_policy(self.manifest.get('intervention_version')),image_asset_equivalence=current)
        self.assessment=assess(self.audit_record['data'],self.preservation,self.verification['data'],self.baseline['data'],fidelity_required=not current,usability=replay['data'] if current else None,review_mode=self.manifest.get('candidate_review_mode','gate'))
        if current and not self.config['single_shot']:
            from remediation_selection import improvement_evidence
            self.improvement=improvement_evidence(self.baseline['data']['axe'],self.baseline['data']['lighthouse'],self.audit_record['data']['axe'],self.audit_record['data']['lighthouse'],self.candidate_taxonomy)
            from .destination_repairs import cases
            from .candidate_repair_context import functional_evidence
            self.state['last_candidate_report']={'candidate_audit_id':self.audit_record['id'],'original':{'axe':self.baseline['data']['axe'],'lighthouse':self.baseline['data']['lighthouse']},
                'candidate':{'axe':self.audit_record['data']['axe'],'lighthouse':self.audit_record['data']['lighthouse']},
                'remaining_lighthouse_failures': self.audit_record['data'].get('lighthouse_failures', []),
                'remaining_taxonomy_failures':{
                    category: values.get('failed', 0)
                    for category, values in self.candidate_taxonomy.get('retained', {}).get('categories', {}).items()
                },
                'taxonomy_coverage': {
                    category: values.get('coverage')
                    for category, values in self.candidate_taxonomy.get('retained', {}).get('categories', {}).items()
                },
                'improvement':self.improvement,'functional_evidence':functional_evidence(self.audit_record,replay['data']),'functional_status':replay['data']['status'],'functional_reasons':replay['data']['reasons'],
                'visual_status':self.verification['data']['status'],'visual_reason':self.verification['data']['rationale'],
                'visual_impact':self.verification['data'].get('impact'),'visual_blocking_confidence':self.verification['data'].get('blocking_confidence'),
                'visual_warnings':self.verification['data'].get('warnings',[]),
                'destination_repairs':cases(self.original,source,self.url,replay['data']['metrics'].get('unverified_destinations',[]))if self.level>=4 else[],
                'assigned_wire_level':self.level,'worker_id':self.worker['id']if getattr(self,'worker',None)else None}
            if self.condition.get('level') == 6:
                from .dynamic_objectives import corrective_evidence
                evidence = corrective_evidence(self.store, self.candidate_taxonomy)
                self.state['last_candidate_report']['unresolved_prior_finding_count'] = evidence['unresolved_prior_finding_count']
        return self.audit_record['data']['raw_result']

    def outcome(self, candidate, retained):
        if retained and self.assessment['status']!='passed' and not self.config['single_shot']:
            raise ContractError('A failed or unverified candidate cannot become the retained result')
        audit=self.audit_record['data']; d=distance(audit['axe'],audit['lighthouse'],self.manifest['targets'])
        if self.manifest.get('refinement_policy')=='budget-only-progress':
            from .progress_continuation import append
            costs = self.costs()
            self.state['progress_history']=append(self.state.get('progress_history',[]),self.baseline['data'],
                {'iteration':self.number,'audit_id':self.audit_record['id'],'axe':audit['axe'],'lighthouse':audit['lighthouse'],'source_words_retained_percent':self.preservation.get('retention',{}).get('text_percent'),
                 'content_retention': {key:self.preservation.get('retention',{}).get(key)
                                       for key in ('text_percent','links_percent','images_percent')},
                 'wire_level':self.level,'worker_id':self.worker['id'],
                 'policy': ('P'+str(wire_to_public(self.level))
                            if self.condition['level']==6 and four_policy(self.manifest.get('intervention_version'))
                            else None),
                 'retained':retained,'cumulative_cost_usd':costs['cost_usd'],
                 'cumulative_input_tokens':costs['input_tokens'],
                 'cumulative_output_tokens':costs['output_tokens']})
            if self.condition.get('level') == 6 and four_policy(self.manifest.get('intervention_version')):
                from .dynamic_objectives import contextual_gain, taxonomy_view
                current = self.state['progress_history'][-1]
                current.update(taxonomy_view((self.candidate_taxonomy or {}).get('retained', {}).get('categories', {})))
                current['unresolved_prior_finding_count'] = self.state['last_candidate_report']['unresolved_prior_finding_count']
                previous = (self.state['progress_history'][-2] if len(self.state['progress_history']) > 1
                            else taxonomy_view((self.candidate_taxonomy or {}).get('original', {}).get('categories', {})))
                if current['direction'] == 'tie' and contextual_gain(previous, current):
                    current['direction'] = 'improved'
                    current['progress_basis'] = 'contextual_failures_at_comparable_coverage'
        if self.condition['level']==6 and self.state.get('last_candidate_report'):
            report=self.state['last_candidate_report']
            report['retained']=retained
            report['content_retention']={key:self.preservation.get('retention',{}).get(key)
                                         for key in ('text_percent','links_percent','images_percent')}
            report['taxonomy_coverage']={category: values.get('coverage')
                for category,values in (self.candidate_taxonomy or {}).get('retained',{}).get('categories',{}).items()}
        blob=self.store.blob(candidate,'candidate_html',self.cid,'text/html')
        case=once(self.store,'technical_assessment',{'run_id':self.rid,'assessment':self.assessment,'audit_id':self.audit_record['id'],'verification_id':self.verification['id']},self.cid,self.attempt_id+'-case')
        once(self.store,'attempt',{'run_id':self.rid,'source_id':blob['id'],'audit_id':self.audit_record['id'],'decision_id':self.decision['id'],
            'retrieval_id':self.retrieval['id'],'before':self.before,'distance':d,'seconds':time.time()-self.attempt_started,
            'level':self.level,'worker_id':self.worker['id'],'retained':retained,'parent_audit_id':self.state['incumbent']['audit_id']},self.cid,self.attempt_id)
        if self.attempt_id not in self.state['attempts']:self.state['attempts'].append(self.attempt_id)
        if retained:
            self.state['incumbent']={'source_id':blob['id'],'audit_id':self.audit_record['id'],'case_id':case['id'],'distance':d,'original':False,
                                    'admissible':self.assessment['status']=='passed','technical':self.assessment['status'],
                                    **({'retention_purpose':'observed-zero-shot-comparator'}if self.config['single_shot'] else{})}
            self.state['stagnant']=0
        else:self.state['stagnant']+=1
        # A measured, syntactically valid proposal can own refinement even when
        # content still needs repair. This does not promote it to the incumbent.
        refinable=(audit.get('status')=='completed' and
                   (self.manifest.get('intervention_version')=='two-patch-creative-regeneration-v2' or self.assessment.get('checks',{}).get('syntax_nonregression',{}).get('state')=='passed'))
        if self.level >= 4 and refinable:
            self.state['branch']={'worker_id':self.worker['id'],'level':self.level,
                                  'source_id':blob['id'],'audit_id':self.audit_record['id']}
        elif self.level < 4:
            self.state.pop('branch',None)
        self.state['last_evaluated_generation_attempt'] = self.number
        self.state['iteration']=self.number;self.persist()
        self.providers.completion_stage = None
        return {'version':VERSION,'level':self.level,'worker_id':self.worker['id'],'decision_id':self.decision['id'],
                'selection':self.decision['data'],'policy_id':self.state['policy_id'],'retrieval_id':self.retrieval['id'],
                'verification_id':self.verification['id'],'assessment':self.assessment,'retained':retained,
                **({'refinement_decision_id':self.state['refinement_decision_id']}if self.state.get('refinement_decision_id')else{}),
                **({'improvement':self.improvement,'candidate_taxonomy':self.candidate_taxonomy}if getattr(self,'candidate_taxonomy',None)is not None else{}),
                'consumption':self.costs(),'original_retained':self.state['incumbent']['original']}

    def costs(self):
        calls=self.providers.ledger.rows(self.cid,self.rid)
        return {'cost_usd':sum(c['cost'] or 0 for c in calls),'input_tokens':sum(c['input_tokens'] or 0 for c in calls),
            'output_tokens':sum(c['output_tokens'] or 0 for c in calls),'known':all(c['cost_status'] in ('provider_reported','reconciled','local') for c in calls),
            'call_ids':[c['id'] for c in calls]}

    def finish(self, stop_reason, measurement_failure=None):
        selected=self.state['incumbent'];audit=self.store.get(selected['audit_id'])['data']
        from accessibility_taxonomy.assessment import measure_pair
        from .run_stop import REASON, requested
        sql_run = getattr(self, 'sql_run', {})
        if sql_run.get('id') is not None and requested(self.store, sql_run['id']):
            stop_reason = REASON
        if stop_reason == REASON:
            taxonomy = {
                'status':'not_assessed','errors':[REASON],
                'baseline_audit_id':self.baseline['id'],'retained_audit_id':selected['audit_id']}
        elif measurement_failure is not None:
            taxonomy={'status':'not_assessed','errors':[str(measurement_failure)],
                      'baseline_audit_id':self.baseline['id'],'retained_audit_id':selected['audit_id']}
        else:
            try:
                taxonomy=measure_pair(self.store,self.providers,self.rid,self.baseline,
                    self.store.get(selected['audit_id']),self.url,self.manifest.get('decision_model'),self.capture)
            except UncertainCall as error:
                # Persist the candidate and incomplete measurement before closing SQL.
                # Unresolved consumption remains in the ledger and blocks new dispatch.
                taxonomy={'status':'not_assessed','errors':[str(error)],
                          'baseline_audit_id':self.baseline['id'],
                          'retained_audit_id':selected['audit_id']}
        from remediation_interventions import VERSION as CURRENT_INTERVENTIONS, four_policy
        costs=self.costs()
        current=self.manifest.get('intervention_version')==CURRENT_INTERVENTIONS
        fidelity=preserved(self.original,self.store.read_blob(selected['source_id']).decode(),self.url,structure_first=True,image_asset_equivalence=True) if current else None
        data={'run_id':self.rid,'page_id':self.page['id'],'condition_id':self.condition['id'],'repetition':0,'partition':self.manifest['partition'],
            'mode':self.manifest['mode'],'policy_id':self.state['policy_id'],'selected':selected,'axe':audit['axe'],'lighthouse':audit['lighthouse'],
            'taxonomy_measurement':taxonomy,'attempts':list(self.state['attempts']),'seconds':time.time()-self.state['started'],
            'unmeasured_proposals':list(self.state.get('unmeasured_proposals', [])),
            'distance':selected['distance'],'preservation':selected['technical'],'evaluation_basis':BASIS,'semantic_preservation':'not_assessed',
            'preserved_success':selected['distance']==0 and selected['technical']=='passed','stop_reason':stop_reason,'costs':costs}
        if current:
            data.update(intervention_version=CURRENT_INTERVENTIONS,source_fidelity=fidelity,preservation=fidelity['status'],candidate_usability=selected['technical'],evaluation_basis='observable-candidate-usability-v1',admissible_success=selected['distance']==0 and selected['technical']=='passed',preserved_success=selected['distance']==0 and selected['technical']=='passed' and fidelity['status']=='passed')
            if self.manifest.get('candidate_review_mode')=='diagnostic-only':
                data.update(evaluation_basis='measured-candidate-diagnostic-review-v1',candidate_review_mode='diagnostic-only',refinement_policy=self.manifest.get('refinement_policy'),quality_reviews_enforced=False)
        if getattr(self,'config',{}).get('single_shot'):
            data.update(comparison_mode='zero-shot',output_policy='record-one-output-without-rejection-or-refinement',
                        output_admission=selected['technical'],evaluation_basis='observed-zero-shot-output; validation-reported')
        if self.state.get('evaluator_consistency_review'):
            data['measurement_consistency'] = self.state['evaluator_consistency_review']
        execution_revision = getattr(self, 'execution_revision', None)
        if execution_revision:
            from .execution_recovery import record_outcome
            data.update(execution_revision_id=execution_revision['id'],
                        generation_runtime_sha256=self.manifest['runtime_snapshot']['code_digest'])
            prior_calls = set(execution_revision['data']['prior_call_ids'])
            data['generation_runtime_by_call'] = {
                call['id']: (execution_revision['data'].get('prior_generation_runtime_by_call', {}).get(
                    call['id'], execution_revision['data']['previous_runtime']['code_digest'])
                    if call['id'] in prior_calls else data['generation_runtime_sha256'])
                for call in self.providers.ledger.rows(self.cid, self.rid)
                if ':call:' in call['logical_key']
            }
            result_record = record_outcome(self.store, execution_revision, data)
        else:
            result_record = once(self.store,'run_result',data,self.cid,self.rid+'-result')
        if taxonomy.get('status')!='completed' and stop_reason != REASON:
            self.state['status']='failed';self.persist()
            raise MeasurementIncomplete('Complementary accessibility measurement is incomplete: '+ '; '.join(taxonomy.get('errors',[])))
        self.state['status']='stopped' if stop_reason == REASON else 'completed';self.persist()
        self.store.checkpoint(self.cid,{'status':'completed','stage':'analysis','pages':[self.page['id']],'runs':[self.rid]})
        return data
