"""Descriptive model/task profiles; co-occurring defects do not identify causation."""
from collections import defaultdict

TASK_RULES = {
    'names-and-attributes': {'image-alt','button-name','link-name','label','html-has-lang','document-title','aria-valid-attr','aria-valid-attr-value'},
    'contrast': {'color-contrast'},
    'nested-structure': {'nested-interactive','list','listitem','definition-list','dlitem','heading-order'},
    'navigation-and-landmarks': {'region','landmark-one-main','page-has-heading-one','landmark-unique','landmark-banner-is-top-level','landmark-contentinfo-is-top-level','bypass'},
    'forms-and-controls': {'label','select-name','input-button-name','input-image-alt','autocomplete-valid','aria-input-field-name','aria-toggle-field-name'},
    'tables': {'td-headers-attr','th-has-data-cells','td-has-header','scope-attr-valid','table-fake-caption'},
}


def tasks(rules):
    rules=set(rules)
    result=sorted(name for name,matching in TASK_RULES.items() if rules & matching)
    if rules-set().union(*TASK_RULES.values()):result.append('other-measured-defects')
    return result or ['no-mapped-defects']


def report(store, campaign, calls):
    manifest=store.get(campaign)['data'];workers={w['id']:w for w in manifest['workers']};groups=defaultdict(list)
    for row in store.list('attempt',campaign):
        attempt=row['data'];decision=store.get(attempt['decision_id'])['data'];action=decision.get('selected','stop')
        if action=='stop':continue
        _,worker_id=action.split(':',1)
        if worker_id not in workers:continue
        worker=workers[worker_id]
        run=store.get(attempt['run_id'])['data'];page=store.get(run['page_id'])['data'];after=store.get(attempt['audit_id'])['data']
        parent_id=attempt.get('parent_audit_id') or page['audit_id'];before=store.get(parent_id)['data']
        assessment=store.get(row['id']+'-case')['data'].get('assessment',{})
        scoped=[c for c in calls if c['logical_key'].startswith((row['id'],attempt['decision_id'],attempt['retrieval_id']))]
        for task in tasks(decision.get('profile',{}).get('rules',[])):
            groups[(task,worker_id)].append({'page':run['page_id'],'run':attempt['run_id'],'attempt':row['id'],
                'axe_change':before['axe']-after['axe'] if before.get('axe') is not None and after.get('axe') is not None else None,
                'lighthouse_change':after['lighthouse']-before['lighthouse'] if before.get('lighthouse') is not None and after.get('lighthouse') is not None else None,
                'status':assessment.get('status','unverified'),'retained':attempt.get('retained'),
                'cost':sum(c['cost'] or 0 for c in scoped),'known':all(c['cost_status'] in ('provider_reported','reconciled','local') for c in scoped),
                'seconds':attempt['seconds'],'category':decision.get('profile',{}).get('category','unknown')})
    rows=[]
    for (task,worker_id),items in sorted(groups.items()):
        def mean(field):
            values=[i[field] for i in items if i[field] is not None]
            return sum(values)/len(values) if values else None
        worker=workers[worker_id]
        rows.append({'task':task,'worker_id':worker_id,'model':worker['model'],'reasoning_effort':worker.get('reasoning_effort'),
            'pages':len({i['page'] for i in items}),'runs':len({i['run'] for i in items}),'attempts':len(items),
            'mean_axe_reduction':mean('axe_change'),'mean_lighthouse_gain':mean('lighthouse_change'),
            'technical_passed':sum(i['status']=='passed' for i in items),'technical_violated':sum(i['status']=='violated' for i in items),
            'technical_unverified':sum(i['status']=='unverified' for i in items),'retained':sum(i['retained'] is True for i in items),
            'cost_usd':sum(i['cost'] for i in items) if all(i['known'] for i in items) else None,'seconds':sum(i['seconds'] for i in items),
            'attempt_ids':[i['attempt'] for i in items],'categories':sorted({i['category'] for i in items})})
    return {'rows':rows,'partition':manifest['partition'],'scope':'Descriptive attempts on co-occurring measured defects; no causal task attribution or model recommendation.',
        'cost_scope':'Worker, selector, retrieval and candidate verifier calls; shared baseline admission reported separately. Costs repeat across co-occurring task rows.'}
