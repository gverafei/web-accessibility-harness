"""Recoverable removal of inactive campaigns; billing and evidence stay durable."""
import json
import time
import uuid
from .contracts import SCHEMA, ContractError, canonical, digest, text
from .store import Conflict

INACTIVE = {'draft', 'completed', 'interrupted', 'blocked', 'paused'}

def visible(store, kind):
    removed = {row['id'] for row in store.list('campaign')
               if store.checkpoint(row['id'])[0].get('status') == 'discarded'}
    return [row for row in store.list(kind)
            if (row['id'] if kind == 'campaign' else row['campaign']) not in removed
            and not store.checkpoint('run-view:'+str(row['data'].get('run_id','')))[0].get('removed')]

def change_run(store, ident, remove=True, revision=None):
    result=store.get(ident+'-result');campaign=result['campaign']
    if result['kind']!='run_result': raise ContractError('Choose a completed run')
    key='run-view:'+ident
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        state=db.execute('SELECT payload FROM checkpoints WHERE id=?',(campaign,)).fetchone()
        if not state or json.loads(state['payload']).get('status') not in INACTIVE|{'discarded'}:
            raise ContractError('Only runs from inactive campaigns can be removed or restored')
        row=db.execute('SELECT * FROM checkpoints WHERE id=?',(key,)).fetchone()
        current=row['revision'] if row else 0
        if revision is not None and revision!=current: raise Conflict('Run view changed; reload before removing or restoring')
        event={'schema':SCHEMA,'run_id':ident,'removed':remove}
        db.execute('INSERT INTO records VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,'run_lifecycle',campaign,canonical(event),digest(event),time.time()))
        db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?,?)',(key,current+1,canonical(event)))

def change(store, ident, remove=True, reason='Researcher removed campaign', revision=None):
    if store.get(ident)['kind'] != 'campaign': raise ContractError('Unknown campaign')
    reason = text(reason, 'removal reason', 1000)
    event_id = uuid.uuid4().hex
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM checkpoints WHERE id=?', (ident,)).fetchone()
        if not row or revision is not None and row['revision'] != revision:
            raise Conflict('Campaign state changed; reload before removing or restoring')
        before = json.loads(row['payload'])
        if remove:
            if before.get('status') not in INACTIVE: raise ContractError('Only inactive campaigns can be removed')
            after = dict(before, status='discarded', discarded_from=before, removal_event_id=event_id)
        else:
            if before.get('status') != 'discarded' or before.get('discarded_from', {}).get('status') not in INACTIVE:
                raise ContractError('Choose a removed campaign to restore')
            after = before['discarded_from']
        event = {'schema': SCHEMA, 'removed': remove, 'reason': reason,
                 'previous_status': before['status'], 'status': after['status']}
        db.execute('INSERT INTO records VALUES (?,?,?,?,?,?)',
                   (event_id, 'campaign_lifecycle', ident, canonical(event), digest(event), time.time()))
        db.execute('UPDATE checkpoints SET revision=?,payload=? WHERE id=?',
                   (row['revision']+1, canonical(after), ident))
    return store.get(event_id)
