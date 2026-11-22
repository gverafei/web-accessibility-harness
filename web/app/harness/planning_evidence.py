"""Lossless sharing of repeated text inside a planner's measured feedback."""
from collections import Counter
from hashlib import sha256
from copy import deepcopy

CHUNK_CHARS = 512
MIN_SHARED_CHARS = 256


def expanded_feedback(feedback):
    """Inverse of shared_feedback; references never silently become missing evidence."""
    from .evidence_sharing import VERSION, expanded_values
    if feedback.get('encoding') == VERSION:
        return expanded_values(feedback)
    if feedback.get('encoding') != 'shared-planning-evidence-v1':
        return deepcopy(feedback)
    pool = feedback['evidence_text_pool']
    def expand(value):
        if isinstance(value, dict):
            if set(value) == {'evidence_text_parts'}:
                return ''.join(part if isinstance(part, str) else pool[part['text_ref']]
                               for part in value['evidence_text_parts'])
            return {key: expand(child) for key, child in value.items()}
        return [expand(child) for child in value] if isinstance(value, list) else value
    return expand(feedback['findings'])


def planner_context(context, *, evidence_version=None):
    """Route choices need findings and resource evidence, not repeated page markup."""
    from .dynamic_objectives import compact_evidence, EVIDENCE_VERSION, SHARED_EVIDENCE_VERSION, SOURCE_BOUND_VERSION, ROLE_BOUND_VERSION, STYLE_EVIDENCE_VERSION
    from .evidence_sharing import shared_values
    result = deepcopy(context)
    state = result.get('state') or {}
    if state.get('measured_feedback'):
        feedback = expanded_feedback(state['measured_feedback'])
        if feedback.get('contextual_findings'):
            feedback['contextual_findings'] = compact_evidence(feedback['contextual_findings'],
                all_markup=evidence_version in (SHARED_EVIDENCE_VERSION, SOURCE_BOUND_VERSION, ROLE_BOUND_VERSION, STYLE_EVIDENCE_VERSION))
        state['measured_feedback'] = (shared_values(feedback) if evidence_version in (SHARED_EVIDENCE_VERSION, SOURCE_BOUND_VERSION, ROLE_BOUND_VERSION, STYLE_EVIDENCE_VERSION)
                                      else shared_feedback(feedback))
    result['evidence_projection_version'] = EVIDENCE_VERSION
    return result


def shared_feedback(feedback):
    """Keep all findings and text; represent repeated chunks only once."""
    counts = Counter()

    def count(value):
        if isinstance(value, str):
            counts.update(value[start:start + CHUNK_CHARS]
                          for start in range(0, len(value), CHUNK_CHARS)
                          if len(value[start:start + CHUNK_CHARS]) >= MIN_SHARED_CHARS)
        elif isinstance(value, dict):
            for child in value.values():
                count(child)
        elif isinstance(value, list):
            for child in value:
                count(child)

    count(feedback)
    repeated = {value for value, occurrences in counts.items() if occurrences > 1}
    if not repeated:
        return feedback
    pool = {}

    def encode(value):
        if isinstance(value, str):
            chunks = [value[start:start + CHUNK_CHARS]
                      for start in range(0, len(value), CHUNK_CHARS)]
            if not any(chunk in repeated for chunk in chunks):
                return value
            parts = []
            literal = ''
            for chunk in chunks:
                if chunk in repeated:
                    if literal:
                        parts.append(literal)
                        literal = ''
                    identifier = sha256(chunk.encode()).hexdigest()
                    pool[identifier] = chunk
                    parts.append({'text_ref': identifier})
                else:
                    literal += chunk
            if literal:
                parts.append(literal)
            return {'evidence_text_parts': parts}
        if isinstance(value, dict):
            return {key: encode(child) for key, child in value.items()}
        if isinstance(value, list):
            return [encode(child) for child in value]
        return value

    encoded = encode(feedback)
    return {
        'encoding': 'shared-planning-evidence-v1',
        'reading_key': ('Read findings normally. evidence_text_parts concatenates literal '
                        'strings and text_ref values from evidence_text_pool in order. '
                        'All original evidence text is retained.'),
        'findings': encoded,
        'evidence_text_pool': pool,
    }
