"""Keep evaluated candidates separate from unevaluated generation attempts."""

VERSION = 'evaluated-candidates-v1'


def counts_candidates(manifest):
    return manifest.get('iteration_policy') == VERSION


def candidate_limit_reached(manifest, state):
    return (counts_candidates(manifest)
            and len(state.get('attempts', [])) >= manifest['max_iterations'])


def generation_limit_reached(manifest, state, number):
    limit = manifest.get('max_generation_attempts_per_candidate')
    last_evaluated = state.get('last_evaluated_generation_attempt', 0)
    return limit is not None and number - last_evaluated > limit


def correcting_proposal(state):
    return (state.get('last_noop') or {}).get('iteration') == state.get('iteration')
