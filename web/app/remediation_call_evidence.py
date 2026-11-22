"""Persist real model-call evidence independently of candidate validation."""
import hashlib
import json
from pathlib import Path


def _ordered_evidence(value):
    """Canonicalize JSON evidence while retaining every non-JSON character."""
    if isinstance(value, list):
        return [_ordered_evidence(item) for item in value]
    if isinstance(value, dict):
        return {key: _ordered_evidence(item) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    decoder = json.JSONDecoder()
    segments = []
    position = cursor = 0
    while cursor < len(value):
        if value[cursor] in '{[':
            try:
                parsed, length = decoder.raw_decode(value[cursor:])
            except ValueError:
                cursor += 1
                continue
            if isinstance(parsed, (dict, list)):
                segments.append(value[position:cursor])
                segments.append(json.dumps(_ordered_evidence(parsed), sort_keys=True,
                                           ensure_ascii=False, separators=(',', ':')))
                cursor += length
                position = cursor
                continue
        cursor += 1
    segments.append(value[position:])
    return ''.join(segments)


def equivalent_planner_failures(first, second):
    """Ignore object-key order only inside the named planner evidence array."""
    prefix = 'You are the information-architecture/accessibility planning specialist, not the generator.'
    marker = '\nFailures: '
    if (not first.startswith(prefix) or not second.startswith(prefix)
            or first.count(marker) != 1 or second.count(marker) != 1):
        return False
    before, left = first.split(marker, 1)
    other_before, right = second.split(marker, 1)
    try:
        original, original_end = json.JSONDecoder().raw_decode(left)
        current, current_end = json.JSONDecoder().raw_decode(right)
    except ValueError:
        return False
    return (before == other_before and isinstance(original, list) and isinstance(current, list)
            and left[original_end:] == right[current_end:]
            and json.dumps(original, sort_keys=True, ensure_ascii=False)
                == json.dumps(current, sort_keys=True, ensure_ascii=False))


def equivalent_patch_prompt(first, second):
    if first == second:
        return True
    # Checkpoint JSON serialization can reorder embedded evidence, including
    # feedback serialized inside another JSON string. Reuse the original bytes
    # only when all values and all surrounding instructions remain identical.
    marker = 'Current evidence:\n'
    if marker in first and marker in second:
        first_prefix, first_tail = first.split(marker, 1)
        second_prefix, second_tail = second.split(marker, 1)
        return (first_prefix == second_prefix
                and _ordered_evidence(first_tail) == _ordered_evidence(second_tail))
    if equivalent_planner_failures(first, second):
        return True
    diagnosis = 'You are the accessibility diagnosis agent BEFORE localized patch generation.'
    if first.startswith(diagnosis) and second.startswith(diagnosis):
        return _ordered_evidence(first) == _ordered_evidence(second)
    return False


def equivalent_patch_messages(first, second):
    if type(first) is not type(second):
        return False
    if isinstance(first, str):
        return equivalent_patch_prompt(first, second)
    if isinstance(first, list):
        return len(first) == len(second) and all(equivalent_patch_messages(a, b) for a, b in zip(first, second))
    if isinstance(first, dict):
        return first.keys() == second.keys() and all(equivalent_patch_messages(first[key], second[key]) for key in first)
    return first == second


class RecordedModelCalls:
    def __init__(self, directory, runtime, caller, resume_existing=False, call_identity=None):
        self.directory = Path(directory)
        self.runtime = runtime
        self.caller = caller
        self.records = []
        self.resume_existing = resume_existing
        self.call_identity = call_identity
        if resume_existing:
            path = self.directory / 'model-call-evidence.json'
            if path.exists():
                document = json.loads(path.read_text())
                if document.get('schema_version') != 'model-call-evidence-v1':
                    raise ValueError('Unknown model-call evidence schema at resumption')
                self.records = document['calls']

    def checkpoint(self):
        document = {'schema_version': 'model-call-evidence-v1',
                    'calls': self.records, 'agentic_runtime': self.runtime.snapshot()}
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / 'model-call-evidence.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)

    def __call__(self, settings, model, prompt, json_mode=False, temperature=None,
                 cost_tier=None, allowed_models=None, messages=None,
                 reasoning_override=None, output_token_limit=None, task_name=None):
        # Never persist settings: they contain provider credentials. Save the
        # exact inputs passed to the transport, including multimodal messages.
        self.last_prompt = prompt
        paid_id = self.call_identity(False) if self.call_identity else None
        if self.resume_existing:
            previous = next((item for item in self.records
                             if item['status'] == 'returned'
                             and (self.call_identity is None or paid_id is not None
                                  and item.get('provider_call_id') == paid_id)
                             and item['requested_model'] == model
                             and equivalent_patch_prompt(item['prompt'], prompt)
                             and equivalent_patch_messages(item['messages'], messages)
                             and item['json_mode'] == json_mode
                             and item['reasoning_override'] == reasoning_override
                             and item['output_token_limit_requested'] == output_token_limit), None)
            if previous:
                self.last_prompt = previous['prompt']
                result = self.caller(settings, model, previous['prompt'], json_mode, temperature,
                                     cost_tier, allowed_models, previous['messages'],
                                     reasoning_override, output_token_limit)
                if hashlib.sha256(result[0].encode()).hexdigest() != previous['response_sha256']:
                    raise ValueError('Replayed model response differs from the saved paid output')
                self.checkpoint()
                return result
        if self.resume_existing and paid_id is not None:
            pending = next((item for item in reversed(self.records)
                            if ((item['status'] == 'transport_failed'
                                 and item.get('error_type') in ('UncertainCall', 'ContractError')
                                 and item.get('pending_call_id', paid_id) == paid_id)
                                or (item['status'] == 'output_incomplete'
                                    and item.get('finish_reason') == 'error'
                                    and item.get('call_id') == paid_id))
                            and item.get('task_name') == task_name
                            and item['requested_model'] == model
                            and equivalent_patch_prompt(item['prompt'], prompt)
                            and equivalent_patch_messages(item['messages'], messages)
                            and item['json_mode'] == json_mode
                            and item['temperature_requested'] == temperature
                            and item['cost_tier'] == cost_tier
                            and item['reasoning_override'] == reasoning_override
                            and item['output_token_limit_requested'] == output_token_limit), None)
            if pending:
                # Restore original serialization only. The transport ledger still
                # requires the exact request hash and an explicit settled retry;
                # this is a real call, not a fabricated or cached response.
                prompt, messages = pending['prompt'], pending['messages']
                self.last_prompt = prompt
        record = {'call_number': len(self.records) + 1, 'stage': self.runtime.state,
                  'status': 'started', 'requested_model': model, 'task_name': task_name, 'prompt': prompt,
                  'messages': messages, 'json_mode': json_mode,
                  'temperature_requested': temperature, 'cost_tier': cost_tier,
                  'reasoning_override': reasoning_override,
                  'output_token_limit_requested': output_token_limit,
                  'model_configuration': settings.get('_model_configuration'),
                  'runtime_before_call': self.runtime.snapshot()}
        if paid_id is not None:
            record['pending_call_id'] = paid_id
        self.records.append(record)
        self.checkpoint()
        try:
            invoke = lambda: self.caller(settings, model, prompt, json_mode, temperature,
                                        cost_tier, allowed_models, messages,
                                        reasoning_override, output_token_limit)
            role = task_name or ('component-planner' if self.runtime.state == 'prompt'
                                 else 'repair-generator')
            result = self.runtime.perform(role, invoke,
                                          ('current_evidence', 'assigned_model', 'output_contract'))
        except Exception as error:
            from harness.contracts import ModelOutputIncomplete
            if isinstance(error, ModelOutputIncomplete):
                incoming, outgoing, cost, seconds, actual_model = error.usage
                record.update(status='output_incomplete', error_type=type(error).__name__,
                              finish_reason=error.reason, input_tokens=incoming, output_tokens=outgoing,
                              cost_usd=cost, seconds=seconds, actual_model=actual_model,
                              call_id=error.call_id, response_id=error.response_id)
            else:
                # A transport failure without a receipt has unknown usage.
                record.update(status='transport_failed', error_type=type(error).__name__)
            self.checkpoint()
            raise
        response, incoming, outgoing, cost, seconds, actual_model = result
        record.update(provider_call_id=self.call_identity(True) if self.call_identity else None,
                      status='returned', response=response,
                      response_sha256=hashlib.sha256(response.encode('utf-8')).hexdigest(),
                      input_tokens=incoming, output_tokens=outgoing,
                      cost_usd=cost, seconds=seconds, actual_model=actual_model)
        self.checkpoint()
        return result
