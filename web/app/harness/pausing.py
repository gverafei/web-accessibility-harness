"""Pause only at durable call boundaries. Billing is never inferred."""
from .contracts import ContractError

class PauseRequested(RuntimeError):pass

def check(store,campaign):
    if store.checkpoint(campaign+'-pause')[0].get('requested'):
        raise PauseRequested('Campaign paused at a durable call boundary')

def request_pause(store,campaign):
    state,_=store.checkpoint(campaign)
    if state.get('status') not in ('queued','running'):raise ContractError('Only active campaigns can be paused')
    store.checkpoint(campaign+'-pause',{'requested':True})
