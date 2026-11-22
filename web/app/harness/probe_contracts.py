"""Fixed synthetic requests shared by pilot preparation and provider checks."""
from .contracts import CRITERIA, canonical

SOURCE = '<html lang="en"><head><title>Page photo</title></head><body><main><p>Page photo</p><img src="https://fixture.example/photo.jpg"></main></body></html>'


def worker_request():
    return {'prompt': 'Return exactly one JSON object with an operations array. '
            'Each operation requires action, selector, name and value. No prose or extra top-level fields. '
            'Set the context-supported alt attribute on img and preserve all other content. '
            'Required envelope: {"operations":[{"action":"set_attribute","selector":"img","name":"alt","value":"Page photo"}]}\nSOURCE\n' + SOURCE,
            'fixture_source': SOURCE}


def judge_request():
    evidence = {'fixture-original': {'role': 'identified synthetic original', 'html': SOURCE},
                'fixture-candidate': {'role': 'identified synthetic candidate',
                                      'html': SOURCE.replace('<img ', '<img alt="Page photo" ')}}
    return {'prompt': 'Evaluate only the acquired observable evidence; this packet is an identified synthetic contract fixture. '
            'Return one JSON object containing ratings, an object keyed by every criterion. '
            'Each criterion requires status (passed|violated|unverified|not_applicable), rationale and evidence_refs. '
            'Use a brief rationale and known evidence_refs. No prose outside JSON. Do not infer hidden live tasks. '
            'Required envelope example: ' + canonical({'ratings': {key: {'status': 'unverified',
                'rationale': 'Brief evidence-grounded assessment', 'evidence_refs': ['fixture-original', 'fixture-candidate']}
                for key in CRITERIA}}) + '\nRUBRIC\n' + canonical(CRITERIA)
            + '\nEVIDENCE\n' + canonical(evidence), 'evidence': evidence}


def decision_request():
    return {'state': 'Synthetic contract fixture: page purpose is article.',
            'questions': [{'name': 'purpose', 'type': 'choice', 'instructions': 'Classify the declared page purpose.',
                           'choices': [{'value': 'article', 'label': 'Article'}, {'value': 'form', 'label': 'Form'}]}]}
