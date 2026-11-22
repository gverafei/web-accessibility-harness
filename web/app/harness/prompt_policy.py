"""Keep adaptive route selection separate from the selected worker's task."""

VERSION = 'selected-strategy-worker-v1'


def shared_strategy_prompt(manifest):
    return manifest.get('worker_prompt_policy') == VERSION
