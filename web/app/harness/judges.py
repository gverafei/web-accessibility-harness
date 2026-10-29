"""Read and reanalyse historical independent judgments; no provider dispatch."""
from .contracts import CRITERIA, STATES, ContractError, decode_json

RUBRIC_VERSION = 'accessibility-preservation-v1'


def parse_rating(value, evidence_ids, criteria=None):
    criteria = list(criteria or CRITERIA)
    value = decode_json(value)
    if not isinstance(value, dict) or set(value.get('ratings', {})) != set(criteria):
        raise ContractError('Judge must answer every requested criterion exactly once')
    result = {}
    for criterion, rating in value['ratings'].items():
        if not isinstance(rating, dict) or rating.get('status') not in STATES:
            raise ContractError('Invalid review state')
        rationale = rating.get('rationale')
        refs = rating.get('evidence_refs')
        if not isinstance(rationale, str) or not 1 <= len(rationale.strip()) <= 2000:
            raise ContractError('A brief evidence-grounded justification is required')
        if not isinstance(refs, list) or not refs or any(ref not in evidence_ids for ref in refs):
            raise ContractError('Rating cites missing or unknown evidence')
        critical=rating.get('critical')
        if critical is not None and (type(critical) is not bool or rating['status']!='violated'):
            raise ContractError('Severity annotations apply only to explicit violations')
        result[criterion] = {'status': rating['status'], 'rationale': rationale, 'evidence_refs': list(dict.fromkeys(refs)), 'critical':critical}
    return result


def consensus(initial, revised=None):
    result = {}
    revised = revised or ({}, {})
    for criterion in CRITERIA:
        answers = [revised[i].get(criterion, initial[i].get(criterion)) for i in range(2)]
        labels = [a.get('status') if a else None for a in answers]
        result[criterion] = {'status': labels[0] if labels[0] is not None and labels[0] == labels[1] else 'unverified',
                             'disagreement': labels[0] != labels[1], 'missing': any(v is None for v in labels),
                             'reconsidered': criterion in revised[0] or criterion in revised[1]}
    return result




def author_annotations(store, case_id):
    rows = [r for r in store.list('author_rating') if r['data']['case_id'] == case_id]
    return {r['data']['author']: r for r in rows}


def annotate(store, campaign, case_id, author, payload, known_ids):
    if author not in ('author_a', 'author_b'):
        raise ContractError('Choose one of the two author identities')
    existing = author_annotations(store, case_id)
    if author in existing:
        raise ContractError('Independent ratings are immutable; use adjudication after both submissions')
    ratings = parse_rating(payload, known_ids)
    return store.append('author_rating', {'case_id': case_id, 'author': author, 'ratings': ratings,
                        'rubric': RUBRIC_VERSION}, campaign, ident=f'{case_id}-{author}')


def adjudicate(store, campaign, case_id, payload, known_ids):
    authors = author_annotations(store, case_id)
    if set(authors) != {'author_a', 'author_b'}:
        raise ContractError('Both independent author ratings must precede adjudication')
    ratings = parse_rating(payload, known_ids)
    return store.append('adjudication', {'case_id': case_id, 'ratings': ratings,
                         'parents': [row['id'] for row in authors.values()], 'rubric': RUBRIC_VERSION}, campaign)
