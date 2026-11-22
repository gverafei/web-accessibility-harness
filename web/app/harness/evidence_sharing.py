"""Self-contained, reversible sharing of repeated evidence values and HTML tags."""
from collections import Counter
from copy import deepcopy
import re

from .contracts import canonical

VERSION = 'shared-evidence-values-v2'
REF = 'evidence_value_ref'
PARTS = 'evidence_text_parts'
LITERAL = 'evidence_literal'


def shared_values(evidence):
    """Share repeated subtrees and markup without removing targets or observations."""
    counts = Counter()

    def visit(value):
        if isinstance(value, (str, dict, list)):
            key = canonical(value)
            if len(key) >= 48:
                counts[key] += 1
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and '<' in value:
            for part in re.split(r'(<[^>]+>)', value):
                if part != value and len(part) >= 48:
                    key = canonical(part)
                    counts[key] += 1

    visit(evidence)
    candidates = {key for key, count in counts.items() if count > 1}
    names = {}
    pool = {}

    def encode(value, *, sharing=True):
        key = canonical(value)
        if sharing and key in candidates:
            if key not in names:
                name = 'v' + str(len(names))
                names[key] = name
                pool[name] = encode(value, sharing=False)
            return {REF: names[key]}
        if isinstance(value, dict):
            result = {k: encode(child) for k, child in value.items()}
            # User evidence may itself contain a codec marker. Preserve it literally.
            return {LITERAL: result} if set(value) in ({REF}, {PARTS}, {LITERAL}) else result
        if isinstance(value, list):
            return [encode(child) for child in value]
        if isinstance(value, str) and '<' in value:
            parts = re.split(r'(<[^>]+>)', value)
            if any(canonical(part) in candidates for part in parts if part != value):
                return {PARTS: [encode(part) if part != value else part for part in parts if part]}
        return value

    encoded = {'encoding': VERSION,
               'reading_key': 'Resolve evidence_value_ref from evidence_value_pool. Concatenate evidence_text_parts in order. evidence_literal escapes a literal object. Every finding, attribute, URL and markup character is retained.',
               'findings': encode(evidence), 'evidence_value_pool': pool}
    return encoded if len(canonical(encoded)) < len(canonical(evidence)) else deepcopy(evidence)


def expanded_values(envelope):
    pool = envelope['evidence_value_pool']

    def expand(value):
        if isinstance(value, dict):
            if set(value) == {REF}:
                return expand(pool[value[REF]])
            if set(value) == {PARTS}:
                return ''.join(expand(part) for part in value[PARTS])
            if set(value) == {LITERAL}:
                return {key: expand(child) for key, child in value[LITERAL].items()}
            return {key: expand(child) for key, child in value.items()}
        return [expand(child) for child in value] if isinstance(value, list) else value

    return expand(envelope['findings'])
