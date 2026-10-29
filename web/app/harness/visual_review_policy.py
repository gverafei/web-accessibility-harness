"""Prospective evidence/impact policy; model certainty is not calibrated accuracy."""
import re

from .contracts import ContractError, decode_json, number

VERSION = 'candidate-visual-confidence-v4'
REJECTION_THRESHOLD = .90
REASONS = {'usable', 'blank', 'blocked', 'unrelated', 'degraded', 'unsupported', 'out_of_scope', 'insufficient'}
IMPACTS = {'none', 'minor', 'material'}

def resolve(reason, impact, confidence):
    if reason not in REASONS or impact not in IMPACTS:
        raise ContractError('Unknown visual review classification or impact')
    if type(confidence) not in (int, float):
        raise ContractError('Visual review requires numeric blocking confidence')
    confidence = number(confidence, 'blocking confidence', 0, 1)
    if (reason == 'usable' and impact == 'material') or (reason not in ('usable', 'insufficient') and impact == 'none'):
        raise ContractError('Visual review classification and impact disagree')
    # Missing usable evidence is not evidence of success. A genuine defect in
    # deterministic resource/target checks remains independently blocking.
    if reason == 'insufficient':
        status = 'review_required'
    elif reason == 'unsupported':
        # Historical provenance suspicions are informational, never a visible
        # failure. Current reviewers no longer judge factual/source support.
        status = 'admitted'
    elif reason == 'usable':
        status = 'admitted'
    elif impact == 'material' and confidence >= REJECTION_THRESHOLD:
        status = 'rejected'
    elif reason in {'blank', 'blocked', 'unrelated', 'out_of_scope'}:
        status = 'review_required'
    else:
        status = 'admitted'
    return {'status': status, 'reason_code': reason, 'impact': impact,
            'blocking_confidence': confidence, 'review_policy': VERSION,
            'rejection_threshold': REJECTION_THRESHOLD,
            'confidence_scope': 'model-estimated probability of a material observable defect; not empirically calibrated',
            'warnings': ['minor_visual_finding'] if status == 'admitted' and reason == 'usable' and impact == 'minor' else [reason] if status == 'admitted' and reason != 'usable' else []}

def parse(value, refs):
    value = decode_json(value)
    normalized=[]
    # v1's prose requested a "brief rationale"; paid answers legitimately used
    # brief_rationale as the field name. Normalize only this exact alias, never
    # infer missing certainty, impact or citations and never discard extras.
    if isinstance(value,dict) and 'brief_rationale' in value and 'rationale' not in value:
        value=dict(value)
        value['rationale']=value.pop('brief_rationale')
        normalized=['brief_rationale -> rationale']
    fields = {'reason_code', 'impact', 'blocking_confidence', 'rationale', 'evidence_refs'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractError('Incomplete confidence-aware visual review')
    rationale = value['rationale']
    citations = value['evidence_refs']
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 2000:
        raise ContractError('Visual review requires a brief grounded rationale')
    if not isinstance(citations, list) or not citations or any(not isinstance(i, str) for i in citations):
        raise ContractError('Visual review cited unknown evidence')
    corrections = []
    resolved = []
    for citation in citations:
        if citation in refs:
            resolved.append(citation)
            continue
        # Opaque UUIDs are evidence handles, not a reasoning task. Correct only
        # one substituted character with ONE match among the supplied handles.
        matches = [reference for reference in refs
                   if re.fullmatch(r'[0-9a-f]{32}', citation)
                   and re.fullmatch(r'[0-9a-f]{32}', reference)
                   and sum(a != b for a, b in zip(citation, reference)) == 1]
        if len(matches) != 1:
            raise ContractError('Visual review cited unknown or ambiguous evidence')
        resolved.append(matches[0])
        corrections.append({'provided':citation,'resolved':matches[0],
                            'basis':'unique one-character substitution among supplied UUIDs'})
    return dict(resolve(value['reason_code'], value['impact'], value['blocking_confidence']),
                rationale=rationale, evidence_refs=resolved,normalized_fields=normalized,
                normalized_references=corrections)

INSTRUCTIONS = (
    'Separate observed facts from suspicions. Identify the most consequential candidate defect, if any, '
    'and explain the exact affected content/control and supplied evidence. A minor isolated detail is minor, '
    'not a material failure of the page. Judge only observable usefulness and visual defects. '
    'Do not judge factual truth or destination provenance, or infer a broken link from absent source support. '
    'blocking_confidence means your estimated probability that the supplied evidence establishes a MATERIAL '
    'observable defect warranting rejection, between 0 and 1; it is not confidence in stylistic preference '
    'or the chance of a successful remote task. A usable page can have a minor isolated defect; use none '
    'when there is no defect, minor for isolated details on an otherwise usable page, material '
    'for substantial unreadability or visibly unusable essential controls. '
    'Use insufficient only when the candidate cannot actually be assessed from the supplied evidence; '
    'a speculative isolated defect on an otherwise visible usable page is not insufficient. '
    'The harness derives status, not the reviewer. It rejects only material defects with blocking confidence '
    'at least 0.90. Minor or uncertain findings remain available for measured refinement. '
    'Missing usable evidence and deterministic failures are not overridden. '
)


def response_schema(refs):
    """Constrain the ordinary vision interface to the supplied evidence handles."""
    return {
        'type':'object',
        'properties':{
            'reason_code':{'type':'string','enum':sorted(REASONS - {'unsupported'})},
            'impact':{'type':'string','enum':sorted(IMPACTS)},
            'blocking_confidence':{'type':'number','minimum':0,'maximum':1},
            'rationale':{'type':'string','description':'Brief explanation grounded in the supplied captures.'},
            'evidence_refs':{'type':'array','minItems':1,
                             'items':{'type':'string','enum':list(dict.fromkeys(refs))}},
        },
        'required':['reason_code','impact','blocking_confidence','rationale','evidence_refs'],
        'additionalProperties':False,
    }
