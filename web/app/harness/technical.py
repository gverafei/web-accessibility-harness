"""Observable checks for core pilots; never a semantic or human judgment."""
from .controller import gate

BASIS = 'observable-technical-v1'


def assess(audit, preservation, verification=None, baseline=None, *, fidelity_required=True, usability=None, review_mode='gate'):
    from .syntax_policy import compare
    syntax = compare(audit.get('syntax'), baseline.get('syntax') if baseline is not None else None)
    status = 'unverified'
    if not fidelity_required:
        # The new method reports fidelity and inherited/new syntax separately.
        # Admission requires actual candidate evidence, never an absent verifier.
        usable=(usability or {}).get('status')
        status='passed' if audit.get('status')=='completed' and usable=='admitted' and (verification or {}).get('status')=='admitted' else 'violated' if usable=='rejected' or (verification or {}).get('status')=='rejected' else 'unverified'
    elif preservation.get('status') == 'violated' or syntax['state'] == 'violated':
        status = 'violated'
    elif gate(audit, preservation, baseline=baseline) and (verification is None or verification.get('status') == 'admitted'):
        status = 'passed'
    if review_mode not in {'gate','diagnostic-only'}:raise ValueError('Invalid candidate review mode')
    diagnostic_status=status
    if review_mode=='diagnostic-only':
        # Ready for measured comparison is not a claim of visual usability.
        # Preserve every independent verdict in checks; only absent/incomplete
        # instrument evidence prevents recording a measured proposal.
        status='passed' if audit.get('status')=='completed' else 'unverified'
    return {'basis': 'measured-candidate-diagnostic-review-v1' if review_mode=='diagnostic-only' else BASIS if fidelity_required else 'observable-candidate-usability-v1', 'status': status, 'semantic_preservation': 'not_assessed',
            'checks': {'audit': audit.get('status'), 'syntax': audit.get('syntax'),
                       'syntax_nonregression': syntax, 'observable_preservation': preservation,
                       'capture_verification': verification, **({'candidate_usability':usability,'source_fidelity_enforced':False} if not fidelity_required else {})},
            'fidelity_required':fidelity_required,
            'review_mode':review_mode, **({'diagnostic_status':diagnostic_status} if review_mode=='diagnostic-only' else {}),
            'scope': 'Measured proposals remain available for comparison; syntax, resources, source fidelity and independent review are diagnostics for bounded refinement, not quality vetoes. Incomplete instrument evidence is not a measured repair.' if review_mode=='diagnostic-only' else 'Recorded syntax, audit, replay and observable content/control contracts.' if fidelity_required else 'Candidate visible content/resources and declared local control contracts plus independent visual review; source fidelity and syntax are reported, not rejection gates. Remote destinations, backend tasks and unobserved handlers are not certified.'}


def status(record):
    """Read the assessment without rewriting historical independent judgments."""
    data = record['data']
    return data.get('assessment', data.get('review', {})).get('status', 'unverified')
