"""Human labels over recorded evidence; no recomputation of scientific outcomes."""
from .providers import Ledger

def run_card(store,row,calls=None):
    data=row['data'];page=store.get(data['page_id'])['data']
    baseline=store.get(page['audit_id'])['data'];audit=store.get(data['selected']['audit_id'])['data']
    manifest=store.get(row['campaign'])['data']
    condition=next(c for c in manifest['conditions'] if c['id']==data['condition_id'])
    worker=next(w for w in manifest['workers'] if w['id']==condition['worker_id'])
    scoped=[c for c in (calls if calls is not None else Ledger(store).rows(row['campaign'])) if c['run']==data['run_id']]
    preview=audit.get('artifacts',{}).get('screenshot') or store.get(page['capture_id'])['data'].get('screenshot_id')
    view,revision=store.checkpoint('run-view:'+data['run_id'])
    return {'row':row,'url':page['source']['url'],'worker':worker['model'],'effort':worker.get('reasoning_effort'),
            'dynamic':condition['level']==6,'baseline':baseline,'preview':preview,'campaign_name':manifest['name'],
            'iterations':len(data.get('attempts',[])), 'cost':sum(c['cost'] or 0 for c in scoped),'pending':sum(c['cost_status']=='unknown' for c in scoped),
            'removed':view.get('removed',False),'revision':revision,
            'can_remove':store.checkpoint(row['campaign'])[0].get('status') in {'draft','completed','interrupted','blocked','discarded'}}

def review_card(store,row):
    page=store.get(row['data']['page_id'])['data'];original=store.get(page['audit_id'])['data']
    candidate=store.get(store.get(row['data']['attempt_id'])['data']['audit_id'])['data'] if row['data'].get('attempt_id') else original
    return {'url':page['source']['url'],'original':original,'candidate':candidate,
            'preview':candidate.get('artifacts',{}).get('screenshot') or store.get(page['capture_id'])['data'].get('screenshot_id')}
