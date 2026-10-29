"""Failure-aware planning and lossless, coordinated repair evidence.

This projection changes advisory inputs, never measurements, edit authority or
paid records. Old manifests keep their original input contracts.
"""
from collections import defaultdict
from copy import deepcopy
import math

from .contracts import canonical, digest
from .planning_evidence import expanded_feedback, shared_feedback

VERSION = 'coordinated-context-repair-v2'
CURRENT_VERSION = 'coordinated-context-repair-v3'
from .source_bound_repair import VERSION as SOURCE_BOUND_VERSION, CURRENT_VERSION as ROLE_BOUND_VERSION
from .repair_style_evidence import VERSION as STYLE_EVIDENCE_VERSION
SUPPORTED_VERSIONS = (VERSION, CURRENT_VERSION, SOURCE_BOUND_VERSION, ROLE_BOUND_VERSION, STYLE_EVIDENCE_VERSION)
REPAIR_INSTRUCTIONS = (
    'Review every supplied finding, including all targets in a same-type group. '
    'Groups reference zero-based indices in failed_opportunities of the expanded evidence. '
    'A group is a coordination candidate, not proof of a shared root cause. Verify '
    'the current source and component evidence before grouping operations. For P2, '
    'coordinate targets with the same verified cause in one proposal when permitted, '
    'instead of repairing an arbitrary first instance. Keep independent causes separate. '
    'Use an observed common component or explicit verified selectors; never generalize '
    'a selector to unverified siblings. Each CSS rule must stay within its declared '
    'target and the existing property/value limits. No new edit permissions are granted. '
    'Shared text references resolve inside evidence_text_pool in this same message; '
    'concatenate evidence_text_parts in order. No content has been omitted. '
)


def enabled(manifest):
    return manifest.get('adaptive_evidence_version') in SUPPORTED_VERSIONS


def repair_projection(evidence, *, version=VERSION):
    """Keep full evidence in-message and index every measured target without guessing CSS."""
    groups = defaultdict(list)
    for index, row in enumerate(evidence.get('failed_opportunities', [])):
        groups[row['type']].append(index)
    from .evidence_sharing import shared_values
    return {
        'version': version,
        'full_evidence_sha256': digest(evidence),
        'same_type_coordination_candidates': [
            {'type': kind, 'failed_opportunity_indices': rows, 'shared_root_cause': 'requires source verification'}
            for kind, rows in sorted(groups.items())],
        'evidence': shared_values(evidence) if version != VERSION else shared_repair_evidence(evidence),
    }


def shared_repair_evidence(evidence):
    """Use short local pool names only when sharing actually reduces the payload."""
    encoded = deepcopy(shared_feedback(evidence))
    if encoded.get('encoding') != 'shared-planning-evidence-v1':
        return encoded
    names = {key: f't{index}' for index, key in enumerate(encoded['evidence_text_pool'])}
    def rename(value):
        if isinstance(value, list):
            return [rename(item) for item in value]
        if isinstance(value, dict):
            if set(value) == {'text_ref'}:
                return {'text_ref': names[value['text_ref']]}
            return {key: rename(child) for key, child in value.items()}
        return value
    encoded['findings'] = rename(encoded['findings'])
    encoded['evidence_text_pool'] = {names[key]: text for key, text in encoded['evidence_text_pool'].items()}
    return encoded if len(canonical(encoded)) < len(canonical(evidence)) else deepcopy(evidence)


def normalize_progress(state):
    """Qualify stale positive signals without rewriting the retained trajectory."""
    result = deepcopy(state)
    feedback = expanded_feedback(result.get('measured_feedback') or {})
    failed = feedback.get('unmeasured_proposal')
    if failed and failed.get('iteration') == result.get('iteration'):
        result['measured_progress_before_last_proposal'] = {
            key: result.get(key) for key in
            ('stagnant', 'continuation_potential', 'continuation_reasons')}
        result['last_proposal'] = {**failed, 'measured': False,
                                   'retained_page_changed': False, 'progress': False}
        history = feedback.get('recent_attempts') or []
        consumption = feedback.get('consumption') or {}
        last_measured = history[-1] if history else {}
        result['last_proposal']['consumption_since_last_measured_candidate'] = {
            field: consumption[field] - last_measured['cumulative_' + field]
            if (isinstance(consumption.get(field), (int, float))
                and isinstance(last_measured.get('cumulative_' + field), (int, float))
                and consumption[field] >= last_measured['cumulative_' + field]) else None
            for field in ('cost_usd', 'input_tokens', 'output_tokens')}
        result['continuation_potential'] = False
        result['continuation_reasons'] = ['last_proposal_invalid_or_unchanged']
        # A failed application is not a measured plateau. Do not manufacture one.
        result['stagnant'] = None
    return result


def replace_context_messages(request, evidence, *, version=VERSION):
    """Project a stored request envelope with the current full repair addendum."""
    from .dynamic_objectives import repair_work, work_messages
    body = deepcopy(request)
    messages = []
    for message in body.get('messages', []):
        content = message.get('content')
        if isinstance(content, str) and content.startswith((
                'Axe 0 and Lighthouse 100 do not complete this adaptive remediation.',
                'Current document contextual findings:', 'Current coordinated repair evidence:')):
            continue
        messages.append(message)
    work = repair_work(evidence, {}, version=version)
    body['messages'] = messages + work_messages(work)
    return body


def request_projection(request, model, observed_call, evidence, *, version=VERSION):
    """Calibrate an estimate on a paid envelope; retain a separate conservative bound."""
    from .providers import input_token_bound
    from model_catalog_metadata import pricing_rates
    body = replace_context_messages(request, evidence, version=version)
    def text_size(value):
        body = deepcopy(value)
        for message in body.get('messages', []):
            if isinstance(message.get('content'), list):
                message['content'] = [part for part in message['content'] if part.get('type') != 'image_url']
        return len(canonical(body).encode()) + 1024
    before = text_size(request)
    upper, images = input_token_bound(body, model)
    tokens = observed_call.get('input_tokens')
    scaled = math.ceil(tokens * text_size(body) / before) if isinstance(tokens, int) and tokens > 0 else None
    estimated = (scaled
                 if isinstance(tokens, int) and tokens > 0 and not images else None)
    estimated_range = ([min(tokens, scaled), max(tokens, scaled)] if scaled is not None and images
                       else [estimated, estimated] if estimated is not None else None)
    allowance = int(body.get('max_tokens') or 0)
    output = observed_call.get('output_tokens')
    input_rate, output_rate = pricing_rates(model, estimated) if estimated is not None else (None, None)
    bound_input_rate, bound_output_rate = pricing_rates(model, upper)
    return {
        'request_id': observed_call['request_id'],
        'reference_call_id': observed_call['id'],
        'reference_input_tokens': tokens,
        'reference_cost_usd': observed_call.get('cost'),
        'projected_request_sha256': digest(body),
        'estimated_input_tokens': estimated,
        'estimated_input_tokens_range': estimated_range,
        'estimated_call_cost_range_usd': [
            (count * pricing_rates(model, count)[0] + output * pricing_rates(model, count)[1]) / 1e6
            for count in estimated_range] if estimated_range is not None and isinstance(output, int) else None,
        'reference_rates_usd_per_million': dict(zip(('input', 'output'), pricing_rates(model, tokens))) if isinstance(tokens, int) else None,
        'input_token_upper_bound': upper,
        'estimated_rates_usd_per_million': {'input': input_rate, 'output': output_rate},
        'pricing_overrides': model.get('pricing_overrides', []),
        'possible_tariff_crossings': [tier['min_prompt_tokens'] for tier in model.get('pricing_overrides', [])
            if estimated_range and estimated_range[0] < tier['min_prompt_tokens'] <= estimated_range[1]],
        'estimated_call_cost_usd': ((estimated * input_rate + output * output_rate) / 1e6
                                  if estimated is not None and isinstance(output, int) else None),
        'call_cost_upper_bound_usd': (upper * bound_input_rate + allowance * bound_output_rate) / 1e6,
        'method': 'Observed envelope token/byte projection with current addendum. For unchanged images the range assigns zero to all reference input tokens to images; image token split and native tokenization are unknown. This is an estimate, not a guaranteed bound.',
        'scope': 'Original envelope/source/advice may differ from the next request. Output estimate uses observed output; upper bound uses its allowance. No truncation or dispatch.'}
