"""Read-only explanations for persisted runtime evidence; not runtime contracts."""
import json
import math
import re
from pathlib import Path

SKILL_COPY = {
    'grounded-accessibility-diagnosis': 'Grounds diagnosis in the current DOM and measured Axe/Lighthouse findings.',
    'minimal-preservation-repair': 'Constrains repairs to small changes while preserving source content and behavior.',
    'coordinated-component-repair': 'Coordinates related components using source order and ownership.',
    'html-born-accessible-regeneration': 'Regenerates a full page from acquired HTML and the selected design base.',
    'markdown-born-accessible-regeneration': 'Regenerates a full page from Markdown and the authoritative UI inventory.',
    'adaptive-evidence-grounding': 'Supplies matching RAG-ACT example pairs from the initial measured repair.',
    'measured-evaluation-and-rollback': 'Measures candidates and deterministically retains the best evaluated result.',
}
EVENT_COPY = {
    'decisions_call': ('LLM response', 'Records the Decisions API choice and actual consumption.'),
    'acquire': ('Software tool', 'Loads the frozen acquisition.'),
    'transform': ('Software tool', 'Prepares the page representation and content inventory.'),
    'markdown': ('Software tool', 'Transforms acquired content into Markdown.'),
    'prompt': ('Software coordinator', 'Assembles instructions and measured feedback for the next call.'),
    'generate': ('LLM stage', 'Requests candidate generation and records its progress.'),
    'planning': ('LLM stage', 'Requests a model plan for grounded components and dependencies.'),
    'planning_response': ('LLM response', 'Persists the returned planning response before validation.'),
    'patch_diagnosis': ('LLM response', 'Records the conditional model diagnosis and its measured usage.'),
    'evaluate': ('Software tool', 'Runs Axe, Lighthouse and the configured optional evaluators.'),
    'metrics': ('Software tool', 'Records measured evaluator and preservation results.'),
    'rag_retrieval': ('Software tool', 'Searches the local RAG-ACT example corpus.'),
    'rag_deferred': ('Software coordinator', 'Records why RAG-ACT retrieval was not used.'),
    'patch': ('Software tool', 'Validates and applies constrained model-proposed operations.'),
    'reconstruction': ('Software tool', 'Assembles the model proposal under source-content contracts.'),
    'invalid_output': ('Software validator', 'Rejects unusable output after recording the actual model call.'),
    'decision': ('Software coordinator', 'Applies the frozen acceptance policy to measured evidence.'),
    'rollback': ('Software coordinator', 'Keeps the best measured candidate after a regression.'),
    'complete': ('Software coordinator', 'Finalizes the run and retains its evaluated result.'),
    'skills_activated': ('Software coordinator', 'Selects versioned procedures and their allowed typed tools.'),
    'plan_validated': ('Software validator', 'Checks component ownership, completeness and source order in the proposed plan.'),
    'patch_diagnosis_skipped': ('Software coordinator', 'Records why no additional model diagnosis was requested.'),
    'budget_stop': ('Software coordinator', 'Stops additional work under the frozen budget.'),
    'plateau_stop': ('Software coordinator', 'Stops refinement after measured improvement has plateaued.'),
    'marginal_stop': ('Software coordinator', 'Stops when measured improvement does not justify another call.'),
    'refine': ('Software coordinator', 'Schedules localized refinement using measured preservation findings.'),
    'evaluation_retry': ('Software tool', 'Retries an incomplete evaluator response without generating a new candidate.'),
    'evaluation_failed': ('Software tool', 'Records the evaluator failure without fabricating measurements.'),
    'widget_replay_normalization': ('Software tool', 'Prepares recognized captured widgets for replay with their frozen data.'),
    'resources_retained': ('Software tool', 'Restores omitted source resources under the content contract.'),
    'no_op': ('Software validator', 'Records an unchanged candidate after validating the proposed operations.'),
    'area_checkpoints': ('Software coordinator', 'Keeps measured area checkpoints for subsequent candidate assembly.'),
    'widget_replay_warning': ('Software validator', 'Records replay limitations detected in captured dynamic controls.'),
    'refinement_interrupted': ('Software coordinator', 'Records an interruption while preserving the best evaluated candidate.'),
    'failed': ('Software coordinator', 'Records a run failure and its original diagnostic evidence.'),
    'accepted': ('Software coordinator', 'Records candidate acceptance under the configured policy.'),
    'extraction_quality': ('Software validator', 'Checks the frozen network and rendered source views for acquisition completeness.'),
    'patch_source_selection': ('Software function', 'Selects the frozen source view used for localized repairs.'),
    'source_hydration': ('Software function', 'Restores captured images in static placeholders from the frozen rendered source.'),
    'unmatched_lighthouse_nodes': ('Software function', 'Records Lighthouse findings that could not be mapped to source elements.'),
}


def load_model_calls(strategy, run_id, dataset_root):
    """Only this run's evidence may be read; never reconstruct absent prompts."""
    path = (strategy.get('model_call_evidence') or {}).get('path')
    if not path:
        return []
    root = (Path(dataset_root) / 'remediations' / str(run_id)).resolve()
    candidate = Path(path).resolve()
    if root not in candidate.parents or candidate.name != 'model-call-evidence.json':
        return []
    try:
        document = json.loads(candidate.read_text(encoding='utf-8'))
        calls = document.get('calls', [])
        return [call for call in calls if isinstance(call, dict)] if isinstance(calls, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def rag_explanation(rag, trace=None):
    """Explain recorded non-use without interpreting an absent trace as success."""
    if not isinstance(rag, dict):
        return 'The reason was not recorded.'
    if rag.get('retrieved'):
        return None
    trace = trace or {}
    if not rag.get('enabled'):
        return 'RAG was disabled for this condition.'
    if trace.get('abstention') == 'no measured defects':
        return 'No measured Axe or Lighthouse failures required examples.'
    if trace.get('method') == 'mapped' and 'mapped_index_candidates' in trace and not trace['mapped_index_candidates']:
        return 'The catalogue had no examples matching the detected criteria.'
    if trace.get('abstention') == 'no complete admissible evidence pair':
        return 'No complete passing/failing example pair met the retrieval criteria.'
    if trace.get('error'):
        return 'Example retrieval failed; no examples were supplied.'
    return 'The reason was not recorded.'


def recorded_questions(questions):
    if isinstance(questions, dict):
        return [{'name':name, 'instructions':q.get('instructions'),
                 'choices':list(q.get('criteria') or [])} for name,q in questions.items() if isinstance(q,dict)]
    return [{'name':q.get('name'), 'instructions':q.get('instructions'),
             'choices':q.get('choices') or q.get('levels') or []} for q in questions if isinstance(q,dict)] if isinstance(questions,list) else []


DECISION_LABELS = {
    'passed':'No violation detected', 'failed':'Violation detected',
    'not_applicable':'Not applicable', 'insufficient_evidence':'Insufficient evidence',
    'usable':'Usable reproduction', 'degraded':'Essential content or appearance lost',
    'blank':'Blank page', 'blocked':'Access blocked', 'unrelated':'Unrelated content',
    'out_of_scope':'Explicit adult content', 'insufficient':'Insufficient evidence',
    'visible_text':'Contrast measurement applies',
    'repair_known_destinations':'Correct verified destinations',
    'continue_local_refinement':'Refine the existing candidate locally',
    'stop':'Stop',
}


def decision_cases(questions, response, locale='en'):
    """Human projection of each recorded question and returned choice, never rejudge."""
    from accessibility_taxonomy import RULES
    from accessibility_taxonomy.explorer import describe
    answers = response.get('answers', {}) if isinstance(response,dict) else {}
    rows = []
    for q in recorded_questions(questions):
        instructions = q.get('instructions') or ''
        observed = {}
        for marker in ('Judge ONLY this observed opportunity: ', 'Evidence: '):
            if marker in instructions:
                try: observed = json.JSONDecoder().raw_decode(instructions.split(marker,1)[1])[0]
                except (ValueError,TypeError): pass
                break
        typ = observed.get('type') if isinstance(observed,dict) else None
        context = observed.get('context',observed) if isinstance(observed,dict) else {}
        if not isinstance(context,dict):context={}
        element = context.get('element') or {}
        attrs = element.get('attributes',{}) if isinstance(element,dict) else {}
        text = next((value for value in (context.get('label'),element.get('text') if isinstance(element,dict) else None,context.get('text'),attrs.get('aria-label'),
                      context.get('observed_text'),context.get('alt')) if isinstance(value,str) and value.strip()), '')
        text = re.sub(r'\s+',' ',text).strip()
        answer = answers.get(q['name'],{}) if isinstance(answers,dict) else {}
        choice = answer.get('choice') if isinstance(answer,dict) else None
        allowed = [v.get('value') if isinstance(v,dict) else v for v in q['choices']]
        result = choice if choice in allowed else 'No usable answer recorded'
        rows.append({'criterion':describe(RULES[typ],locale)['criterion'] if typ in RULES else None,
                     'category':RULES.get(typ,{}).get('category'),
                     'choices':[DECISION_LABELS.get(value,str(value)) for value in allowed],
                     'element':(text[:180]+'…' if len(text)>180 else text) or 'Not recorded',
                     'result':DECISION_LABELS.get(result,result)})
    return rows


def iteration_presentation(item, run_id, dataset_root):
    strategy = item.get('strategy') or {}
    rag = strategy.get('rag') or {}
    trace = None
    if rag.get('retrieval_id') and not rag.get('retrieved'):
        from harness.store import Store
        try:
            record = Store().get(rag['retrieval_id'])
            if record['kind'] == 'retrieval' and record['data'].get('run_id') == 'sql-run-'+str(run_id):
                trace = record['data']
        except KeyError:
            pass
    item['rag_explanation'] = rag_explanation(rag, trace)
    item['retention_summary'] = retention_summary(strategy.get('content_retention') or (strategy.get('source_fidelity')or{}).get('retention'))
    visual = (strategy.get('candidate_selection') or {}).get('visual_similarity_percent')
    item['visual_similarity_percent'] = visual if (
        isinstance(visual, (int, float)) and not isinstance(visual, bool)
        and math.isfinite(visual) and 0 <= visual <= 100) else None
    runtime = strategy.get('agentic_runtime') or {}
    contracts = {row['name']: row for row in runtime.get('tool_contracts', []) if isinstance(row, dict) and row.get('name')}
    item['runtime_skills'] = [dict(row, description=SKILL_COPY.get(row.get('id'),
        'Executes a recorded versioned procedure; consult its technical evidence for the contract.'))
        for row in runtime.get('iteration_skills', []) if isinstance(row, dict)]
    item['runtime_tools'] = [dict(row, description=(contracts.get(row.get('tool')) or {}).get('description') or
        'Executes the recorded typed software operation; not a model call.')
        for row in runtime.get('tool_invocations', []) if isinstance(row, dict)]
    item['model_calls'] = load_model_calls(strategy, run_id, dataset_root)
    from remediation_output_format import recorded_output_format
    item['recorded_output_format']=recorded_output_format(item.get('output_path'),run_id,dataset_root)
    item['selection_summary'] = {'level':strategy.get('public_level',strategy.get('assigned_level')),
        'model':item.get('generator_model') or strategy.get('harness',{}).get('worker_id'),
        'retained':strategy.get('harness',{}).get('retained')}
    selection = strategy.get('harness',{}).get('selection') or {}
    item['selection_summary'].update(category=(selection.get('context',{}).get('profile',{}) or selection.get('profile',{})).get('category'),
        explanation={'fixed':'Level and model fixed by the run configuration.', 'decisions':'Decisions selected the intervention and model using the recorded context and remaining resources.'}.get(selection.get('selector'),'Not recorded'))
    checks = strategy.get('harness',{}).get('assessment',{}).get('checks',{})
    item['display_validation_checks']=checks
    from harness.store import Store
    try:
        revision=Store().get('selection-review-v1-sql-run-'+str(run_id)+'-iteration-'+str(item.get('id')))
        data=revision['data']
        if revision['kind']=='selection_review_revision' and data.get('run_id')=='sql-run-'+str(run_id) and data.get('iteration_id')==item.get('id'):
            item['selection_review']=data
            item['display_validation_checks']=data['checks']
    except KeyError:
        pass
    item['validation_findings'] = [{'check':key.replace('_',' ').capitalize(), 'result':value}
        for key,value in checks.items() if isinstance(value,(str,bool,int,float))] if isinstance(checks,dict) else []
    item['pipeline_stages'] = []
    for name, evidence in (strategy.get('stage_accounting') or {}).items():
        calls = evidence.get('llm_calls')
        cost = evidence.get('cost_usd')
        if calls == 0 and not float(evidence.get('seconds') or 0) and not float(cost or 0) and name in {'planning', 'diagnosis'}:
            continue
        kind = 'LLM calls' if calls else ('External evaluator' if name == 'automated_evaluation' and float(cost or 0) else 'Software tool')
        item['pipeline_stages'].append(dict(evidence, name=name, kind=kind))


def retention_summary(evidence):
    """Read-only, equally weighted UI summary; never an acceptance/ranking gate."""
    evidence = evidence if isinstance(evidence, dict) else {}
    definitions = (
        ('Words', 'original_words', 'candidate_words', 'text_percent'),
        ('Links', 'original_links', 'candidate_links', 'links_percent'),
        ('Images', 'original_images', 'candidate_images', 'images_percent'),
        ('Banners and media', 'dynamic_images_required', 'dynamic_images_retained', 'dynamic_images_percent'),
    )
    rows, percentages = [], []
    for label, source, candidate, metric in definitions:
        value = evidence.get(metric)
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 100
        if valid and metric in ('text_percent','links_percent','images_percent'):
            percentages.append(value)
        rows.append({'label':label, 'source':evidence.get(source),
                     'candidate':evidence.get(candidate), 'percent':value if valid else None})
    return {'percent':round(sum(percentages)/len(percentages),2) if percentages else None,
            'measures':len(percentages), 'rows':rows}


def decision_activity_events(run, events, store, timezone, locale='en'):
    """Project existing Decisions receipts; no SQL event writes or provider calls."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    try:
        config = run.get('harness_config_json') or {}
        if isinstance(config, str): config = json.loads(config)
        campaign = config.get('campaign_id')
    except (ValueError, TypeError, AttributeError):
        return events
    if not campaign: return events
    try:
        outcome=run.get('harness_outcome') or json.loads(run.get('harness_outcome_json') or '{}')
        archived_keys=(outcome.get('iteration_trace_correction') or {}).get('archived_call_keys',[])
    except (ValueError,TypeError,AttributeError):archived_keys=[]
    run_id='sql-run-'+str(run['id'])
    scopes=[(campaign,run_id)]
    for kind in ('taxonomy_measurement_revision','retention_revision'):
        for revision in store.list(kind,campaign):
            data=revision['data']
            if data.get('outcome',{}).get('run_id')==run_id and data.get('measurement_campaign_id'):
                scopes.append((data['measurement_campaign_id'],data.get('measurement_run_id',run_id)))
    with store.connect() as db:
        if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='calls'").fetchone(): return events
        calls=[];seen=set()
        for scope in scopes:
            for row in db.execute('SELECT * FROM calls WHERE campaign=? AND run=? ORDER BY created,id',scope):
                if row['id']not in seen:calls.append(dict(row));seen.add(row['id'])
    projected = list(events)
    existing_ids = {e.get('id') for e in events}
    for call in calls:
        # Instrument-error attempts are archived explicitly; their immutable
        # receipts still count in accounting and technical downloads.
        if call['logical_key'] in archived_keys:continue
        ident = 'provider-call-'+call['id']
        if ident in existing_ids: continue
        try: request = store.get(call['request_id'])['data']['request']
        except KeyError: continue
        structured=bool(request.get('questions'))
        if not structured and not ('verification'in call['logical_key'] or call['logical_key'].startswith('taxonomy-')):continue
        response = {}
        if call.get('response_id'):
            try: response = json.loads(store.read_blob(call['response_id']))
            except (KeyError,ValueError,OSError): pass
        cases = decision_cases(request['questions'],response,locale)if structured else[]
        key = call['logical_key']
        role = ('Level and model selection' if key.endswith(':selector') else
                'RAG example relevance' if 'rerank' in key else
                'Local refinement planning' if 'refinement' in key else
                'Capture verification' if 'verification' in key else
                'Page classification' if 'category' in key else
                'Complementary taxonomy evaluation' if key.startswith('taxonomy-') else 'Recorded decision')
        if role == 'Complementary taxonomy evaluation' and cases and all(c['category']=='Semantic' for c in cases):
            role = 'Semantic evaluation'
        for case in cases:
            if case['element']=='Not recorded' and request.get('state'):
                case['element'] = ('Original and frozen replay' if key.startswith('sql-source') else 'Original and repair candidate') if role=='Capture verification' else 'Supplied page evidence'
        selection = None
        if key.endswith(':selector'):
            try: selection = store.get(key.removesuffix(':selector'))['data'].get('selected')
            except KeyError: pass
        cost = ('US$'+format(call['cost'], '.6f')) if call['cost'] is not None else 'unknown'
        message = f"{role}: {selection or call['status']} · {call['input_tokens'] if call['input_tokens'] is not None else '?'} input / {call['output_tokens'] if call['output_tokens'] is not None else '?'} output tokens · {cost} ({call['cost_status']})"
        projected.append({'id':ident,'actor':'Decisions agent'if structured else'Visual review agent'if role=='Capture verification'else'Image-purpose judge','event_type':'decisions_call'if structured else'llm_call',
            'created_at':datetime.fromtimestamp(call['created'], ZoneInfo(timezone)).replace(tzinfo=None),
            'message':message,'decision_role':role,'decision_choice':selection or call['status'],
            'decision_cases':cases,
            'decision_input_tokens':call['input_tokens'],'decision_output_tokens':call['output_tokens'],
            'decision_cost':cost,'decision_cost_status':call['cost_status'],
            'details_json':{'model':call['model'],'call_id':call['id'],'request_id':call['request_id'],'response_id':call['response_id']}})
    return sorted(projected, key=lambda event: event['created_at'])


def event_presentation(event):
    try:
        details = event.get('details_json') or {}
        if isinstance(details, str):
            details = json.loads(details)
        if not isinstance(details, dict):
            details = {}
    except (ValueError, TypeError):
        details = {}
    kind, description = EVENT_COPY.get(event.get('event_type'),
        ('Software activity', 'Records a pipeline operation.'))
    if event.get('event_type') in ('decisions_call','llm_call'):
        kind='LLM stage'
        description = {
            'Capture verification': 'Decide whether the original and replayed page preserve essential content, styling, images and controls.',
            'Level and model selection': 'Choose the next intervention level and model configuration, or stop, using the page context, results and remaining budget.',
            'Local refinement planning': 'Choose whether to correct verified destinations, refine the existing candidate locally or stop, using its measured results and concrete repair evidence.',
            'RAG example relevance': 'Decide which retrieved examples are relevant to the measured accessibility failures.',
            'Page classification': 'Choose the page category from the available categories.',
            'Semantic evaluation': 'Evaluate the meaning and purpose of each element in this batch.',
            'Complementary taxonomy evaluation': 'Judge the accessibility criteria for this batch of elements: violation, no violation, not applicable or insufficient evidence.',
        }.get(event.get('decision_role'), 'Answer the recorded closed questions using the supplied evidence.')
    category, label = {
        'LLM stage': ('llm', 'LLM'), 'LLM response': ('llm', 'LLM'),
        'Software tool': ('tool', 'Tool'), 'External evaluator': ('tool', 'Tool'),
        'Software coordinator': ('control', 'Control'),
        'Software validator': ('validation', 'Validation'),
        'Software function': ('function', 'Function'),
    }.get(kind, ('function', 'Function'))
    message = event.get('message') or ''
    if event.get('actor') == 'Acceptance coordinator':
        # Display only: keep frozen feedback and the original event intact.
        message = re.split(r'\b(?:Axe failures|Measured Axe failures|Lighthouse accessibility failures|Automated preservation evidence)\s*:',
                           message, maxsplit=1, flags=re.IGNORECASE)[0].rstrip()
        message = message.split('Refine the preceding candidate using the exact evidence below.', 1)[0].rstrip(' :\n')
    if len(message)>800 or re.search(r'<(?:html|body|script|style)\b|\{\s*"',message,re.IGNORECASE):
        message = 'Full technical details are available in the JSON download.'
    event.update(activity_kind=kind, activity_description=description,
                 activity_category=category, activity_label=label,
                 activity_message=message,
                 activity_model=details.get('model') if kind.startswith('LLM') else None)


def live_loop_participants(events):
    """Recorded actors/calls only; tools and procedures are not invented LLMs."""
    roles={'Capture verification':'preserve','Level and model selection':'selection',
           'Local refinement planning':'selection','RAG example relevance':'evidence',
           'Page classification':'context','Semantic evaluation':'taxonomy',
           'Complementary taxonomy evaluation':'taxonomy'}
    types={'acquire':'context','source_preparation':'context','transform':'context','markdown':'context',
           'extraction_quality':'context','prompt':'evidence','rag_retrieval':'evidence','rag_deferred':'evidence',
           'skill_orchestration':'repair','planning':'repair','patch_diagnosis':'repair',
           'generate':'repair','patch':'repair','invalid_output':'repair','no_op':'repair',
           'reconstruction':'repair','evaluate':'audit','metrics':'audit','decision':'retain',
           'rollback':'retain','refine':'retain','complete':'retain','accepted':'retain'}
    stages={key:{'calls':0,'cases':0,'actors':[]}for key in ('context','selection','repair','evidence','audit','taxonomy','retain','preserve')}
    latest=None
    for event in events:
        key=roles.get(event.get('decision_role')) if event.get('event_type')in('decisions_call','llm_call')else types.get(event.get('event_type'))
        if key not in stages:key=latest or 'context'
        latest=key;stage=stages[key];stage['calls']+=1
        stage['cases']+=len(event.get('decision_cases')or[])
        actor={'name':event.get('actor')or'Agent','kind':event.get('activity_label')or'Tool',
               'category':event.get('activity_category')or'tool','model':event.get('activity_model'),
               'event_id':str(event.get('id')),'identity':(event.get('actor')or'Agent')+'|'+str(event.get('activity_model')or''),'calls':1}
        labels=(('image','Image review'),('skill','Skills'),('rag','RAG'),('retriev','RAG'),('decision','Decisions'),('generator','Generator'),('patch','Patch'),('evaluation','Audit'),('evaluator','Audit'),('verification','Vision'),('visual','Vision'),('transform','Transform'),('context','Context'),('preserv','Checks'))
        actor['short']=next((label for token,label in labels if token in actor['name'].lower()),actor['name'])
        known=next((r for r in stage['actors']if r['name']==actor['name']and r['model']==actor['model']),None)
        if known:
            known.update(calls=known['calls']+1,event_id=actor['event_id'])
            stage['actors'].remove(known);stage['actors'].append(known)
        else:stage['actors'].append(actor)
    latest_activity = ((events[-1].get('activity_description') if events[-1].get('activity_category')=='llm'
                        else events[-1].get('activity_message') or events[-1].get('activity_description'))
                       if events else None)
    if events and events[-1].get('event_type') == 'invalid_output':
        latest_activity = 'The proposal failed validation. Correcting it before evaluation.'
    elif events and events[-1].get('event_type') == 'no_op':
        latest_activity = 'The proposal made no effective change. No new candidate was evaluated.'
    return {'stages':stages,'current':latest,'latest_activity':latest_activity}


def live_provider_activity(store, run_id):
    """Display actual ledger dispatch/response state, including recovery calls."""
    calls=[]
    with store.connect() as db:
        if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='calls'").fetchone():
            calls=[dict(row) for row in db.execute('SELECT * FROM calls WHERE run=? ORDER BY created,id',('sql-run-'+str(run_id),))]
    projected=[]
    for call in calls:
        try: model=store.get(call['request_id'])['data']['model']
        except KeyError: model={}
        provider=model.get('provider') if isinstance(model,dict) else None
        key=call['logical_key'].lower()
        stage=('taxonomy' if 'taxonomy' in key else 'selection' if 'selector' in key or 'refinement' in key else 'preserve' if 'verif' in key or 'visual' in key else 'evidence' if 'relevance' in key else 'repair' if call['account']=='repair' else 'context')
        projected.append({'id':call['id'],'model':call['model'],'vendor':{'openai':'OpenAI','anthropic':'Anthropic'}.get(call['model'].split('/')[0],call['model'].split('/')[0]),
                          'provider':{'openrouter':'OpenRouter','openai':'OpenAI','ollama':'Ollama'}.get(provider,provider or 'Recorded provider'),'stage':stage,
                          'pending':call['status']=='dispatching',
                          'returned':bool(call.get('response_id')),'status':call['status']})
    active=[call for call in projected if call['pending']]
    return {'active':active,'latest':projected[-1] if projected else None,'count':len(projected)}


def retained_progress(run, iteration_number=None, axe=None, lighthouse=None,
                      translate=lambda text, **values: text % values if values else text):
    """One concise projection from the actual retained result, never latest/best."""
    if run.get('status') in ('queued','running','failed'):
        return progress_presentation(run.get('progress_message'),translate)
    if run.get('status') == 'stopped':
        return translate('Stopped by user. Recorded results and charges were preserved.')
    if run.get('execution_mode')=='single_shot' and run.get('recorded_output_format')=='no-html-document':
        return translate('Raw zero-shot response retained · no HTML document returned')
    if run.get('accepted_iteration_id') is not None and iteration_number is not None:
        return translate('Iteration %(number)s chosen · Axe %(axe)s · Lighthouse %(lighthouse)s',
            number=iteration_number,axe=axe if axe is not None else '—',
            lighthouse=lighthouse if lighthouse is not None else '—')
    try:
        outcome=run.get('harness_outcome') or json.loads(run.get('harness_outcome_json') or '{}')
    except (ValueError,TypeError):outcome={}
    if outcome.get('selected',{}).get('original') is True:
        return translate('Original retained · Axe %(axe)s · Lighthouse %(lighthouse)s',
            axe=axe if axe is not None else '—',lighthouse=lighthouse if lighthouse is not None else '—')
    return progress_presentation(run.get('progress_message'),translate)


def progress_presentation(message, translate=lambda text, **values: text % values if values else text):
    """Translate recorded progress without rewriting runtime evidence."""
    message=message or ''
    match=re.fullmatch(r'Evaluating candidate (\d+) with (.+)',message)
    if match:
        return translate('Evaluating candidate %(number)s with %(tools)s',number=match[1],tools=match[2])
    match=re.fullmatch(r'(.+): generating candidate (\d+)',message)
    if match:
        return translate('%(strategy)s: generating candidate %(number)s',strategy=translate(match[1]),number=match[2])
    return translate(message) if message else ''


def best_measured(run, iterations):
    """Display-only best audit; acceptance/retention records remain independent."""
    candidates=[project for item in iterations for project in [__import__('axe_metrics').project_wcag(item)]
                if project.get('axe_violations') is not None and project.get('lighthouse_score') is not None]
    def key(item):
        axe=float(item['axe_violations']); lh=float(item['lighthouse_score'])
        return (max(axe-float(run.get('max_axe') or 0),0)+max(float(run.get('min_lighthouse') or 0)-lh,0),
                axe,-lh,item.get('iteration_number') or 0)
    return min(candidates,key=key) if candidates else None


def target_presentation(run, item):
    """Correct display of target attainment, without changing historical decisions."""
    axe=item.get('axe_violations');lh=item.get('lighthouse_score')
    item['targets_met']=(axe is not None and axe<=run['max_axe'] and lh is not None and lh>=run['min_lighthouse']
        and (run.get('min_aim') is None or item.get('wave_aim_score') is not None and item['wave_aim_score']>=run['min_aim']))
    item['technical_status']=item.get('selection_review',{}).get('assessment_status')or item.get('strategy',{}).get('harness',{}).get('assessment',{}).get('status')
    checks = item.get('display_validation_checks') or item.get('strategy', {}).get('harness', {}).get('assessment', {}).get('checks', {})
    item['visual_review'] = visual_review_presentation(checks)


def visual_review_presentation(checks):
    """Expose the saved visual judgment independently of technical selection."""
    visual = checks.get('capture_verification') or {}
    status = visual.get('status')
    if (status == 'rejected' and (checks.get('candidate_usability') or {}).get('status') == 'rejected'
            and not visual.get('evidence_refs')):
        status = 'not_performed'
    if status not in ('admitted', 'rejected', 'review_required', 'not_performed'):
        status = 'not_recorded'
    return {'status': status, 'recorded': status != 'not_recorded'}


def iteration_ordinals(iterations):
    """Number measured candidates continuously without changing raw attempts."""
    ordered = sorted(iterations, key=lambda item: (item.get('iteration_number') or 0, item['id']))
    return {item['id']: number for number, item in enumerate(ordered, 1)}


def retained_candidate(run, iterations):
    """Coordinator retention is authoritative, including historical SQL mismatches."""
    raw=run.get('harness_outcome_json')
    try:outcome=json.loads(raw) if isinstance(raw,str) else raw or {}
    except (ValueError,TypeError):outcome={}
    selected=outcome.get('selected') or {}
    if selected.get('original'):
        return None
    ident=selected.get('sql_iteration_id')
    audit=selected.get('audit_id') or ''
    match=re.fullmatch(r'sql-run-(\d+)-attempt-(\d+)-audit',audit)
    if match and int(match[1])==run.get('id'):
        number=int(match[2])+1
        return next((item for item in iterations if item.get('iteration_number')==number),None)
    ident=ident or run.get('accepted_iteration_id')
    return next((item for item in iterations if item.get('id')==ident),None)


def retained_summary(run, iterations):
    item=retained_candidate(run,iterations)
    if item:return __import__('axe_metrics').project_wcag(item)
    raw=run.get('harness_outcome_json')
    try:outcome=json.loads(raw) if isinstance(raw,str) else raw or {}
    except (ValueError,TypeError):outcome={}
    if outcome.get('selected',{}).get('original'):
        return {'id':None,'original':True,'axe_violations':outcome.get('axe'),
                'lighthouse_score':outcome.get('lighthouse'),'wave_aim_score':None,
                'dom_distance':0.0 if outcome.get('distance') == 0 else None}
    return None


def failure_category(run):
    if run.get('status')!='failed':return None
    error=(run.get('error_message') or '').lower()
    if any(word in error for word in ('capture','replay','instrument','stored source','cdn.jsdelivr','evaluator')):return 'Instrument failure'
    if any(word in error for word in ('provider','429','consumption','charge')):return 'Provider failure'
    return 'Generation failure'


def execution_counts(run, iterations):
    """Separate measured versions from proposal attempts, including no-op attempts."""
    generated = [item for item in iterations if item.get('generator_provider') != 'system']
    attempts = max([int(run.get('current_iteration') or 0)] +
                   [int(item.get('iteration_number') or 0) for item in generated])
    evaluated = sum(item.get('axe_violations') is not None or
                    item.get('lighthouse_score') is not None for item in generated)
    return {'attempts': attempts, 'evaluated': evaluated,
            'limit': int(run.get('max_iterations') or 0)}
