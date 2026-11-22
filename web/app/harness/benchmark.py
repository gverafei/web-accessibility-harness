"""Bounded complete relevance references; partial annotations never imply global recall."""
from .contracts import ContractError, digest
from .retrieval import bounded_benchmark, relevance_metrics

def create(store, corpus_id, profile, candidate_ids, size, seed, campaign='', retrieval_id=None):
    corpus = store.get(corpus_id)
    if corpus['kind']!='corpus': raise ContractError('Select a corpus snapshot')
    rows = bounded_benchmark(corpus['data']['examples'],candidate_ids,size,seed)
    return store.append('relevance_case', {'corpus_id':corpus_id,'corpus_hash':corpus['hash'],'profile':profile,
                        'universe':rows,'seed':seed,'retrieval_id':retrieval_id,
                        'query_digest':digest(store.get(retrieval_id)['data']['query']) if retrieval_id else None,'scope':'bounded exhaustively annotated reference; not the entire corpus'},campaign)

def annotations(store, case_id):
    return {r['data']['author']:r for r in store.list('relevance_rating') if r['data']['case_id']==case_id}

def annotate(store, case_id, author, ratings):
    case=store.get(case_id)
    if case['kind']!='relevance_case' or author not in ('author_a','author_b'): raise ContractError('Invalid relevance reviewer or case')
    if author in annotations(store,case_id): raise ContractError('Independent relevance annotations are immutable')
    universe=case['data']['universe']
    if set(ratings)!=set(universe): raise ContractError('Annotate every example in the bounded collection')
    for key,value in ratings.items():
        if type(value.get('relevant')) is not bool or not isinstance(value.get('rationale'),str) or not value['rationale'].strip():
            raise ContractError('Each example needs relevance and a grounded rationale')
    return store.append('relevance_rating',{'case_id':case_id,'author':author,'ratings':ratings},case['campaign'],case_id+'-'+author)

def adjudicate(store, case_id, ratings):
    authors=annotations(store,case_id)
    if len(authors)!=2: raise ContractError('Both authors must annotate before adjudication')
    case=store.get(case_id)
    if set(ratings)!=set(case['data']['universe']) or any(type(v.get('relevant')) is not bool or not v.get('rationale') for v in ratings.values()):
        raise ContractError('Adjudicate every example with evidence')
    return store.append('relevance_reference',{'case_id':case_id,'ratings':ratings,'parents':[r['id'] for r in authors.values()],
                        'corpus_id':case['data']['corpus_id'],'profile':case['data']['profile']},case['campaign'])

def oracle_ids(store, reference_id, profile):
    reference=store.get(reference_id)
    if reference['kind']!='relevance_reference': raise ContractError('Oracle requires an adjudicated relevance reference')
    data=reference['data']
    def signature(p): return {k:p.get(k) for k in ('source_url','purpose','repair_context','rules')}
    if digest(signature(data['profile']))!=digest(signature(profile)): raise ContractError('Oracle reference does not match the acquired page/defect context')
    return [key for key,value in data['ratings'].items() if value['relevant']]

def report(store, case_id, retrieval_id):
    case=store.get(case_id); retrieval=store.get(retrieval_id)
    refs=[r for r in store.list('relevance_reference') if r['data']['case_id']==case_id]
    if not refs: raise ContractError('An adjudicated bounded reference is required')
    from .relevance import reference_metrics
    return reference_metrics(case,retrieval,refs[-1])
