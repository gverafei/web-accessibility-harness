"""Approved provider-contract probes on identified synthetic evidence, not repair outcomes."""
from .contracts import ContractError
from .controller import materialize, preserved
from .probe_contracts import SOURCE, worker_request, decision_request


def execute(store, manifest, campaign, providers):
    def save(key, action):
        ident=campaign+'-probe-'+key
        try:return store.get(ident)
        except KeyError:pass
        data=action(ident)
        return store.append('contract_probe',{'role':key,'provenance':'synthetic provider-contract evidence; not a page-remediation observation',**data},campaign,ident)
    results=[]
    for slot, model in enumerate(manifest['workers']):
        def worker(key, model=model):
            request=worker_request()
            output=providers.chat(campaign+'-probes','repair',key+':worker',model,request['prompt'])
            candidate,_=materialize(SOURCE,output,1,'https://fixture.example/')
            checks=preserved(SOURCE,candidate,'https://fixture.example/')
            if checks['status']!='passed':raise ContractError('Synthetic worker probe violates its preservation contract')
            return {'model_digest':model['digest'],'typed_response':True,'preservation':checks,'fixture_source':SOURCE,'candidate_html':candidate}
        results.append(save('worker-'+str(slot),worker)['id'])
    def decision(key):
        request=decision_request()
        answer=providers.decisions(campaign+'-probes','repair',key+':decision',request['state'],request['questions'])
        if answer['purpose'].get('type')=='refusal':raise ContractError('Decision contract probe refused')
        return {'model_digest':manifest['decision_model']['digest'],'typed_response':True,'answer':answer,'fixture_state':request['state']}
    results.append(save('decision',decision)['id'])
    return results
