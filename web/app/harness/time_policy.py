"""A wall-time budget gates iteration starts, never unfinished admitted work."""
import math

ITERATION_BOUNDARY = 'finish-started-iteration-and-taxonomy-v1'
BUDGET_PROGRESS = 'budget-only-progress-v1'
CANDIDATE_BOUNDARY = 'finish-started-candidate-budget-v1'
STAGES = frozenset(('iteration', 'taxonomy'))


def finishes_stage(manifest, stage):
    return manifest.get('time_policy') in (ITERATION_BOUNDARY,BUDGET_PROGRESS,CANDIDATE_BOUNDARY) and stage in STAGES


def effective_limits(limits, manifest, stage):
    if manifest.get('time_policy') == CANDIDATE_BOUNDARY:
        return {**limits, 'max_calls': math.inf,
                'max_seconds': math.inf if finishes_stage(manifest, stage) else limits['max_seconds']}
    if manifest.get('time_policy')==BUDGET_PROGRESS:
        # This policy treats time, iteration and call counts as soft limits.
        # Per-request, account, run and shared USD reservations stay unchanged.
        return {**limits,'max_seconds':math.inf,'max_calls':math.inf}
    # Transient adapter state only. Monetary, context and call guards stay hard.
    return {**limits, 'max_seconds': math.inf} if finishes_stage(manifest, stage) else limits
