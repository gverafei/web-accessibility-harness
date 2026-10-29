"""Evidence-derived campaign reports; repeated runs are clustered by acquired page."""
from collections import defaultdict
from .relevance import relevance_reports
from .providers import Ledger


def current_measurements(store,campaign,runs,calls):
    from .contracts import ContractError
    revisions = sorted(
        store.list('taxonomy_measurement_revision', campaign)
        + store.list('retention_revision', campaign)
        + store.list('source_fidelity_revision', campaign)
        + store.list('iteration_accounting_revision', campaign)
        + store.list('execution_recovery_result', campaign)
        + store.list('zero_shot_output_revision', campaign)
        + store.list('zero_shot_delivery_revision', campaign)
        + store.list('zero_shot_delivery_timing_revision', campaign)
        + store.list('taxonomy_consistency_revision', campaign),
        key=lambda row: (row['created'], row['id']),
    )
    revisions = [row for row in revisions if row['kind'] not in ('iteration_accounting_revision', 'zero_shot_output_revision', 'zero_shot_delivery_revision')
                 or store.checkpoint(row['id'] + '-application')[0].get('committed') is True]
    originals={r['id']:r for r in runs};by_id={r['id']:r for r in revisions};roots={}
    identity=('run_id','page_id','condition_id','repetition','intervention_version')
    def root_of(ident,trail=()):
        if ident in originals:return ident
        if ident in roots:return roots[ident]
        if ident in trail or ident not in by_id:raise ContractError('Revision requires an acyclic recorded outcome lineage')
        row=by_id[ident];parent=row['data']['parent_outcome_id'];root=root_of(parent,trail+(ident,))
        if parent in by_id and by_id[parent]['created']>=row['created']:raise ContractError('Revision cannot refer to a future parent')
        if any(row['data']['outcome'].get(k)!=originals[root]['data'].get(k)for k in identity):raise ContractError('Revision cannot change the original run identity')
        roots[ident]=root;return root
    for row in revisions:root_of(row['id'])
    # A metadata correction can supersede unusable historical revision envelopes.
    # They remain immutable and their charges remain counted. Only a later, fully
    # validated revision of the same root may replace them in the active report.
    superseded=set()
    for row in revisions:
        for ident in row['data'].get('supersedes_revision_ids',[]):
            if ident not in by_id or roots[ident]!=roots[row['id']] or by_id[ident]['created']>=row['created']:
                raise ContractError('Revision supersession must be earlier evidence of the same run')
            superseded.add(ident)
    revised={}
    applied=[]
    for revision in revisions:
        parent=roots[revision['id']]
        original=originals[parent]
        outcome=revision['data']['outcome']
        if original is None or any(outcome.get(k)!=original['data'].get(k)for k in ('run_id','page_id','condition_id','repetition','intervention_version')):
            raise ContractError('Revision cannot change the original run identity')
        if revision['id'] in superseded:
            applied.append(revision)
            continue
        incumbent=revised[parent]['data']['outcome']if parent in revised else original['data']
        if revision['kind'] == 'taxonomy_consistency_revision':
            from accessibility_taxonomy.consistency_resolution import validate_revision
            validate_revision(store, revision, incumbent)
        elif revision['kind'] == 'execution_recovery_result':
            from .execution_recovery import validate_outcome_revision
            validate_outcome_revision(store, revision, incumbent, calls)
        elif revision['kind'] == 'zero_shot_output_revision':
            from .zero_shot_revision import validate_revision
            validate_revision(store, revision, incumbent, calls)
        elif revision['kind'] == 'zero_shot_delivery_revision':
            from .zero_shot_delivery import validate_revision
            validate_revision(store, revision, incumbent, calls)
        elif revision['kind'] == 'zero_shot_delivery_timing_revision':
            from .zero_shot_delivery import validate_timing_revision
            validate_timing_revision(store, revision, incumbent, calls)
        elif revision['kind'] == 'iteration_accounting_revision':
            from .iteration_accounting import validate_revision
            validate_revision(store, revision, incumbent, calls)
        elif revision['kind']in ('taxonomy_measurement_revision','source_fidelity_revision'):
            if outcome['selected']!=incumbent['selected']:
                raise ContractError('Measurement revision cannot change the retained run')
            if revision['kind']=='source_fidelity_revision'and any(outcome.get(k)!=incumbent.get(k)for k in ('axe','lighthouse','taxonomy_measurement','candidate_usability','admissible_success','attempts')):
                raise ContractError('Fidelity revision cannot change accessibility, admission or measured taxonomy')
        else:
            correction=outcome.get('retention_revision')or{}
            selected=outcome.get('selected')or{}
            try:
                case=store.get(selected['case_id']);audit=store.get(selected['audit_id'])
                verification=store.get(case['data']['verification_id'])
                assessment=case['data']['assessment']
                assert selected.get('admissible')is True and selected.get('original')is False and selected.get('technical')=='passed'
                assert case['kind']=='technical_assessment'and case['data']['audit_id']==audit['id']and audit['kind']=='audit'and audit['data']['status']=='completed'
                assert verification['data']['status']=='admitted'and verification['data']['audit_id']==audit['id']
                assert assessment['status']=='passed'
                from remediation_interventions import VERSION
                if original['data'].get('intervention_version')==VERSION:
                    assert assessment.get('fidelity_required')is False
                    assert assessment['checks']['candidate_usability']['status']=='admitted'
                    assert assessment['checks']['capture_verification']['status']=='admitted'
                else:
                    assert assessment['checks']['syntax_nonregression']['state']=='passed'
                    assert assessment['checks']['observable_preservation']['status']=='passed'
                assert correction.get('no_generation')is True and correction.get('original_execution_reusable_as_corrected_policy')is False
                assert revision['data'].get('raw_receipts_modified')is False
            except (AssertionError,KeyError,TypeError):
                raise ContractError('Retention revision requires bound admissible candidate evidence')
        revised[parent]=revision
        applied.append(revision)
    updated=[dict(r,data=revised[r['id']]['data']['outcome']) if r['id']in revised else r for r in runs]
    seen={c['id']for c in calls}
    for revision in applied:
        run_id=revision['data']['outcome']['run_id']
        measurement_run=revision['data'].get('measurement_run_id',run_id)
        for call in Ledger(store).rows(revision['data'].get('measurement_campaign_id',campaign),measurement_run):
            if call['id'] not in seen:
                calls.append(dict(call,run=run_id,revision_run_id=call['run'])if measurement_run!=run_id else call);seen.add(call['id'])
    excluded = {ident for revision in applied if revision['kind'] in ('iteration_accounting_revision', 'zero_shot_output_revision')
                for ident in revision['data']['excluded_call_ids']}
    return updated,[call for call in calls if call['id'] not in excluded],[r['id']for r in applied]


def campaign_report(store,campaign):
    manifest=store.get(campaign)['data']; calls=Ledger(store).rows(campaign)
    runs,calls,revisions=current_measurements(store,campaign,store.list('run_result',campaign),calls)
    from .analysis import outcomes,contrasts as paired_outcomes
    measured=outcomes(store,manifest,runs,calls); summaries=[]
    for condition in manifest['conditions']:
        selected=[r for r in measured if r['condition_id']==condition['id']]
        row={'condition':condition['id'],'n':len(selected),'pages':len({r['page_id'] for r in selected}),
             'preserved_success':sum(r['preserved_success'] for r in selected),
             'admissible_success':sum(r.get('admissible_success',r['preserved_success']) for r in selected),
             'violated':sum(r['preservation']=='violated' for r in selected),'unverified':sum(r['preservation']=='unverified' for r in selected),
             'original_retained':sum(r['selected']['original'] for r in selected)}
        ids={r['run_id'] for r in selected}; scoped=[c for c in calls if c['run'] in ids]
        row.update(cost_usd=sum(c['cost'] or 0 for c in scoped),calls=len(scoped),
                   input_tokens=sum(c['input_tokens'] or 0 for c in scoped),output_tokens=sum(c['output_tokens'] or 0 for c in scoped),
                   unresolved_cost=sum(c['cost_status'] not in ('provider_reported','reconciled','local') for c in scoped),
                   seconds=sum(r['seconds'] for r in selected),learning_calls=sum(c['account']=='learning' for c in scoped))
        summaries.append(row)
    contrasts=[]
    for i,a in enumerate(manifest['conditions']):
        for b in manifest['conditions'][i+1:]:
            paired=defaultdict(dict)
            for run in runs:
                d=run['data']
                if d['condition_id'] in (a['id'],b['id']): paired[(d['page_id'],d['repetition'])][d['condition_id']]=d
            rows=[(p, values[b['id']]['preserved_success']-values[a['id']]['preserved_success'])
                  for (p,rep),values in paired.items() if set(values)=={a['id'],b['id']}]
            declared=next((c for c in manifest['analysis']['contrasts'] if c['first']==a['id'] and c['second']==b['id']),None)
            contrasts.append({'first':a['id'],'second':b['id'],'hypothesis':declared['hypothesis'] if declared else 'exploratory',
                              'metrics':paired_outcomes(measured,a['id'],b['id'])})
    from .model_tasks import report as model_tasks
    return {'model_tasks':model_tasks(store,campaign,calls),'evaluation_basis':manifest.get('evaluation_basis','two-judge-consensus'),'schema':'a11yharness/1','manifest_hash':store.get(campaign)['hash'],'conditions':summaries,'contract_probes':[r['data'] for r in store.list('contract_probe',campaign)],
            'denominators':{'requested_pages':manifest['source']['count'],'acquired_pages':len(store.list('page',campaign)),
                'planned_runs':0 if manifest['capture_only'] or manifest.get('provider_probe') else manifest['source']['count']*manifest['repetitions']*len(manifest['conditions']),
                'completed_runs':len(runs),'started_runs':len(store.list('run',campaign)),
                'view_removed_runs':sum(bool(store.checkpoint('run-view:'+r['data']['run_id'])[0].get('removed')) for r in runs)},
            'author_samples':[r['data'] for r in store.list('author_sample',campaign)],
            'measurement_revisions':revisions,'outcomes':measured,'relevance':relevance_reports(store,campaign),'paired_contrasts':contrasts,
            'acquisition_failures':len(store.list('acquisition_failure',campaign)),
            'pending_calls':[c['id'] for c in calls if c['cost_status'] not in ('provider_reported','reconciled','local')],
            'scope':'Measured software outcomes only; no unobserved actions or real study results are inferred.'}
