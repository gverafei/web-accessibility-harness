"""Pinned vector collection and cached metadata; independent relevance measurement."""
import math
import re
from collections import defaultdict
from functools import lru_cache
import requests

from remediation_rag import AXE_ACT_TERMS, embed, _features, prompt_context
from .contracts import ContractError, digest


def measured_concepts(audit):
    """Use known Lighthouse correspondences without relabelling its audit as Axe."""
    defects = list(audit.get('failures', []))
    seen = {item.get('id', item.get('rule')) for item in defects}
    for item in audit.get('lighthouse_failures', []):
        rule = item.get('audit', item.get('id'))
        if rule in AXE_ACT_TERMS and rule not in seen:
            defects.append({'id': rule, 'evaluator': 'lighthouse', 'evidence': item})
            seen.add(rule)
    return defects


def snapshot_collection(store, collection, endpoint, metadata, session=requests):
    rows, seen = [], set()
    offset = None
    for _ in range(100):
        body = {'limit': 1000, 'with_payload': True, 'with_vector': False}
        if offset is not None:
            body['offset'] = offset
        response = session.post(endpoint.rstrip('/') + '/collections/' + collection + '/points/scroll', json=body, timeout=15)
        response.raise_for_status()
        page = response.json()['result']
        for point in page['points']:
            item = {**point['payload'], 'id': str(point['id'])}
            if item['id'] in seen:
                raise ContractError('Repeated point in corpus snapshot')
            seen.add(item['id']); rows.append(item)
        offset = page.get('next_page_offset')
        if offset is None:
            break
    else:
        raise ContractError('Corpus pagination is incomplete')
    if not rows:
        raise ContractError('Initialize a nonempty attributed corpus first')
    return store.append('corpus', {'collection': collection, 'endpoint': endpoint,
                        'metadata': metadata, 'examples': sorted(rows, key=lambda r: r['id']),
                        'content_digest': digest(rows), 'source': 'pinned vector collection'})


@lru_cache(maxsize=8)
def _cached_index(path, record_id, record_hash):
    from .store import Store
    row = Store(path).get(record_id)
    if row['hash'] != record_hash:
        raise ContractError('Corpus snapshot changed')
    examples=row['data']['examples']
    by_id={item['id']:item for item in examples}
    by_name=defaultdict(list)
    for item in examples: by_name[str(item.get('rule_name') or '').casefold()].append(item)
    return examples,by_id,dict(by_name)


class Retriever:
    def __init__(self, store, corpus_id, session=requests, vector_search=None):
        self.store, self.record = store, store.get(corpus_id)
        if self.record['kind'] != 'corpus':
            raise ContractError('Select an immutable corpus snapshot')
        self.examples,self.by_id,self.by_name = _cached_index(str(store.root), corpus_id, self.record['hash'])
        self.session, self.vector_search = session, vector_search

    def vectors(self, query, limit):
        if self.vector_search:
            return self.vector_search(query, limit)
        data = self.record['data']
        response = self.session.post(data['endpoint'].rstrip('/') + '/collections/' + data['collection'] + '/points/query',
                                     json={'query': embed(query), 'limit': limit, 'with_payload': False}, timeout=8)
        response.raise_for_status()
        return [{'id': str(p['id']), 'score': p['score']} for p in response.json()['result']['points']]

    def retrieve(self, query, failures, k=4, method='mapped', rerank=None, oracle_ids=None):
        requested_rules = [f.get('id', f.get('rule')) for f in failures]
        names = {AXE_ACT_TERMS[rule].casefold() for rule in requested_rules if rule in AXE_ACT_TERMS}
        trace = {'corpus_id': self.record['id'], 'corpus_hash': self.record['hash'], 'query': query,
                 'requested_rules': requested_rules, 'method': method, 'k': k,
                 'candidates': [], 'filtered': [], 'injected': [], 'semantic_embedding': False}
        if not failures:
            trace['abstention'] = 'no measured defects'
            return [], trace
        if oracle_ids is not None:
            candidates = [{'id': ident, 'score': 1.} for ident in oracle_ids]
        else:
            candidates = self.vectors(query, min(48, k * 4))
        if any(item['id'] not in self.by_id for item in candidates):
            raise ContractError('Vector result is outside the pinned corpus snapshot')
        trace['candidates'] = candidates
        trace['mapped_index_candidates'] = [item['id'] for name in sorted(names) for item in self.by_name.get(name,[])] if method!='legacy' else []
        tokens = set(_features(query))
        ranked = []
        # Legacy compares the old wider neighbourhood; corrected mapping has a cached exact index.
        pool = [self.by_id[item['id']] for item in candidates] if method == 'legacy' else [item for name in sorted(names) for item in self.by_name.get(name,[])]
        if oracle_ids is not None:
            pool = [self.by_id[ident] for ident in oracle_ids]
        for item in pool:
            name = str(item.get('rule_name') or '').casefold()
            reason = None
            if oracle_ids is None and name not in names:
                reason = 'not applicable to a mapped measured concept'
            elif len(str(item.get('code') or '')) > 5000:
                reason = 'complete example exceeds context limit'
            elif item.get('expected') not in ('passed', 'failed'):
                reason = 'unsupported example outcome'
            if reason:
                if any(c['id'] == item['id'] for c in candidates):
                    trace['filtered'].append({'id': item['id'], 'reason': reason})
                continue
            score = 6 * len(tokens & set(_features(name))) + 2 * len(tokens & set(_features(item.get('title', ''))))
            score += 50 if name in query.casefold() else 0
            ranked.append({**item, 'score': float(score)})
        ranked.sort(key=lambda row: (-row['score'], row['id']))
        if method == 'decisions' and ranked and rerank:
            ranked, decision_trace = rerank(ranked[:48])
            trace['reranking'] = decision_trace
        groups = defaultdict(list)
        for item in ranked:
            groups[item.get('rule_id')].append(item)
        chosen = []
        for items in groups.values():
            pair = [next((item for item in items if item['expected'] == expected), None) for expected in ('passed', 'failed')]
            if all(pair) and len(chosen) + 2 <= k:
                chosen.extend(pair)
        trace['retrieved'] = [{'id': item['id'], 'score': item['score']} for item in ranked]
        trace['injected'] = [item['id'] for item in chosen]
        if not chosen:
            trace['abstention'] = 'no complete admissible evidence pair'
        return chosen, trace

    @staticmethod
    def grounding(items):
        return prompt_context(items)


from .relevance import relevance_metrics


def bounded_benchmark(examples, candidates, size, seed):
    import random
    ordered = sorted({item['id'] for item in examples})
    included = list(dict.fromkeys(candidates))
    if any(ident not in ordered for ident in included) or size < len(included):
        raise ContractError('Benchmark size must cover its candidates')
    if size > len(ordered): raise ContractError('The corpus cannot supply the requested bounded collection size')
    remaining = [ident for ident in ordered if ident not in included]
    included += random.Random(str(seed)).sample(remaining, min(size - len(included), len(remaining)))
    return included
