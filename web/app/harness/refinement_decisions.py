"""Closed next-action review for an existing regenerated branch."""
from .contracts import ContractError,canonical

VERSION='evidence-guided-local-refinement-v1'


def choose(store,providers,run,ident,model,evidence):
    try:return store.get(ident)
    except KeyError:pass
    choices=[{'value':'continue_local_refinement','description':'Repair the existing candidate locally using its measured functional, visual and accessibility findings; retain its design.'},
             {'value':'stop','description':'Stop only when no supported useful local repair remains or evidence/resources are insufficient.'}]
    if evidence.get('destination_repairs'):
        choices.insert(0,{'value':'repair_known_destinations','description':'Apply only the listed exact source-supported destination corrections, then evaluate the same design again. Perfect audit scores do not make incorrect links acceptable.'})
    questions=[{'name':'action','type':'choice','instructions':'Choose the next useful action for this particular candidate. An in-target original or candidate is not a reason to stop while a verified local correction remains. Source omissions are reported, not restoration obligations. Never choose or invent an unlisted destination.','choices':choices}]
    answers=providers.decisions(run,'repair',ident+':agent',canonical(evidence),questions,model=model)
    action=answers.get('action',{}).get('choice')
    if action not in {row['value']for row in choices}:raise ContractError('Invalid local refinement decision; no inferred action')
    return store.append('local_refinement_decision',{'version':VERSION,'run_id':run,'evidence':evidence,'answers':answers,'action':action,
        'scope':'Choose continuation within the assigned intervention/worker and deterministic permissions; never admit a candidate or alter budgets.'},providers.campaign,ident)
