"""Raw paired outcomes, independent gates and configurable PRE sensitivity."""
from collections import Counter
from .statistics import paired_interval
from .contracts import semantic_status

def pre(run, baseline, cost, known, settings, weight=None):
    if run['preservation']=='unverified' or not known or run.get('axe') is None or run.get('lighthouse') is None: return None
    if run.get('candidate_usability',run['preservation'])=='violated': return 0.
    w=settings['axe_weight'] if weight is None else weight
    ga=max(-1,min(1,(baseline['axe']-run['axe'])/max(1,baseline['axe'])))
    gl=(run['lighthouse']-baseline['lighthouse'])/100
    q=w*ga+(1-w)*gl
    return max(0,q)/(1+cost/settings['cost_reference']+run['seconds']/settings['time_reference'])

def issue_changes(before,after):
    def counts(failures): return Counter(f['id'] for f in failures for _ in f.get('nodes',[]))
    a,b=counts(before),counts(after)
    return {'corrected':dict(a-b),'introduced':dict(b-a),'corrected_instances':sum((a-b).values()),'introduced_instances':sum((b-a).values())}

def outcomes(store,manifest,runs,calls):
    rows=[]
    for record in runs:
        run=dict(record['data']);run.setdefault('preservation','unverified');run['online_preservation']=run['preservation'];run['assessment_source']=run.get('evaluation_basis','two-judge-consensus')
        page=store.get(run['page_id']);baseline=store.get(page['data']['audit_id'])['data']
        audit=store.get(run['selected']['audit_id'])['data'] if run['selected'].get('audit_id') else None
        scoped=[c for c in calls if c['run']==run['run_id']]
        known=all(c['cost_status'] in ('provider_reported','reconciled','local') for c in scoped)
        cost=(run['costs']['cost_usd'] if run.get('resource_scope')=='cleaned-experimental-execution'
              else sum(c['cost'] or 0 for c in scoped))
        attempts=[store.get(i)['data'] for i in run['attempts']]
        cases=[store.get(i+'-case')['data'] for i in run['attempts']] if audit else []
        changes=(issue_changes(baseline['failures'],audit['failures']) if audit else
                 {'corrected':{},'introduced':{},'corrected_instances':None,'introduced_instances':None})
        rows.append(run | changes | {'baseline_axe':baseline['axe'],'baseline_lighthouse':baseline['lighthouse'],
             'cost_usd':cost,'cost_scope':'provider API charges; local compute costs excluded','cost_verified':known,'PRE':pre(run,baseline,cost,known,manifest['analysis']),
             'PRE_sensitivity':{str(w):pre(run,baseline,cost,known,manifest['analysis'],w) for w in (.25,.5,.75)},
             'proposed_violations':sum(c.get('assessment',c.get('review',{})).get('status','unverified')=='violated' for c in cases),
             'proposed_unverified':sum(c.get('assessment',c.get('review',{})).get('status','unverified')=='unverified' for c in cases),
             'proposal_count':len(attempts) if audit else 0})
    return rows

def contrasts(rows,first,second):
    pairs={}
    for row in rows:
        if row['condition_id'] in (first,second):pairs.setdefault((row['page_id'],row['repetition']),{})[row['condition_id']]=row
    complete=[(page,values) for (page,rep),values in pairs.items() if set(values)=={first,second}]
    report={}
    for metric in ('preserved_success','axe','lighthouse','cost_usd','seconds','PRE','proposed_violations','corrected_instances','introduced_instances'):
        differences=[(p,v[second][metric]-v[first][metric]) for p,v in complete if v[first].get(metric) is not None and v[second].get(metric) is not None]
        report[metric]=paired_interval(differences) | {'paired_runs':len(differences),'excluded_pairs':len(complete)-len(differences)}
    return report
