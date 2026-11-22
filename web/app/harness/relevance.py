"""Pure relevance arithmetic and trace-derived reports, shared with offline export."""
from .contracts import ContractError, digest

def relevance_metrics(retrieved_ids, injected_ids, judgments, universe_ids, k):
    if type(k) is not int or k < 1:
        raise ContractError('Relevance k must be a positive integer')
    universe = set(universe_ids)
    if set(judgments) - universe:
        raise ContractError('Judgment outside the benchmark collection')
    judged = {ident: label for ident, label in judgments.items() if type(label) is bool}
    relevant = {ident for ident, label in judged.items() if label}
    complete = set(judged) == universe
    def stage(ids):
        ranked = list(dict.fromkeys(ids))
        considered = [ident for ident in ranked if ident in universe]
        top = ranked[:k]
        known = [ident for ident in considered if ident in judged]
        top_known = [ident for ident in top if ident in judged]
        return {'retrieved': len(ranked), 'judged': len(known),
                'precision': sum(ident in relevant for ident in ranked) / len(ranked) if ranked and all(ident in judged for ident in ranked) else None,
                'judged_precision': sum(ident in relevant for ident in known) / len(known) if known else None,
                'precision_at_k': sum(ident in relevant for ident in top) / k if len(top_known) == len(top) and complete else None,
                'recall_at_k': sum(ident in relevant for ident in top) / len(relevant) if complete and relevant else None,
                'empty': not ranked, 'outside_reference': len(set(ranked) - universe)}
    return {'reference_scope': 'fully annotated bounded collection' if complete else 'incomplete bounded collection',
            'collection_size': len(universe), 'judged': len(judged), 'coverage': len(judged) / len(universe) if universe else 0,
            'relevant': len(relevant), 'no_relevant_examples': complete and not relevant,
            'retrieved': stage(retrieved_ids), 'injected': stage(injected_ids), 'k': k}


def reference_metrics(case, retrieval, reference):
    if retrieval['data']['corpus_id'] != case['data']['corpus_id']:
        raise ContractError('Corpus snapshots do not match')
    if case['data'].get('query_digest') and case['data']['query_digest'] != digest(retrieval['data']['query']):
        raise ContractError('Relevance reference belongs to a different measured query context')
    if reference['data']['case_id'] != case['id']:
        raise ContractError('Relevance reference belongs to a different benchmark')
    labels = {key: value['relevant'] for key, value in reference['data']['ratings'].items()}
    trace = retrieval['data']
    ids = [item['id'] if isinstance(item, dict) else item for item in trace.get('retrieved', [])]
    metrics = relevance_metrics(ids, trace['injected'], labels, case['data']['universe'], trace.get('k', 4))
    vector_ids = [item['id'] for item in trace.get('candidates', [])]
    metrics['vector_candidates'] = relevance_metrics(vector_ids, [], labels, case['data']['universe'], trace.get('k', 4))['retrieved']
    return metrics


def relevance_reports(store, campaign):
    """Include unannotated queries explicitly; compare only matching frozen queries."""
    traces = store.list('retrieval', campaign)
    cases = store.list('relevance_case')
    references = store.list('relevance_reference')
    result = []
    for trace in traces:
        matching = [case for case in cases if case['data']['corpus_id'] == trace['data']['corpus_id'] and
                    (case['data'].get('query_digest') == digest(trace['data']['query']) or
                     not case['data'].get('query_digest') and case['data'].get('retrieval_id') == trace['id'])]
        base = {'retrieval_id': trace['id'], 'method': trace['data']['method'],
                'run_id': trace['data'].get('run_id'), 'query_digest': digest(trace['data']['query'])}
        if not matching:
            result.append(base | {'status': 'unannotated', 'metrics': None})
        for case in matching:
            refs = [ref for ref in references if ref['data']['case_id'] == case['id']]
            if not refs:
                result.append(base | {'case_id': case['id'], 'status': 'pending_adjudication', 'metrics': None})
            else:
                result.append(base | {'case_id': case['id'], 'reference_id': refs[-1]['id'],
                                     'status': 'adjudicated', 'metrics': reference_metrics(case, trace, refs[-1])})
    return result
