"""Bounded HTTP adapters. The durable ledger precedes dispatch and output parsing."""
import json
import math
import time
import uuid
import requests
import re
import copy
import base64
from contextlib import contextmanager

from .contracts import ContractError, canonical, decode_json, digest, number
from .store import Conflict

class BudgetStop(RuntimeError):
    pass


class UncertainCall(RuntimeError):
    pass


def bind_provider_route(body, model):
    """Apply an optional frozen OpenRouter route before accounting and dispatch."""
    route = model.get('provider_route')
    if route is None:
        return body
    default = {'allow_fallbacks': False, 'require_parameters': True}
    if body.get('provider') not in (None, default, route):
        raise ContractError('The frozen provider route cannot be overridden')
    return {**body, 'provider': copy.deepcopy(route)}


def input_token_bound(request, model):
    """Bound text and typed images separately; inline transport is not text."""
    framed=copy.deepcopy(request);image_tokens=0;images=0;unknown_images=False
    for message in framed.get('messages',[]):
        content=message.get('content')
        if isinstance(content,list):
            for part in content:
                if part.get('type')=='image_url' and isinstance(part.get('image_url'),dict):
                    image=part['image_url'];detail=image.get('detail','auto')
                    known=model.get('vision_token_bounds',{}).get(detail)
                    if known is None:unknown_images=True
                    else:image_tokens+=known
                    image['url']='[image input]';images+=1
        if message.get('images'):
            images+=len(message['images']);unknown_images=True
            message['images']=['[image input]']*len(message['images'])
    for part in framed.get('state',[]) if isinstance(framed.get('state'),list) else []:
        if isinstance(part,dict) and part.get('type')=='image_url' and isinstance(part.get('image_url'),dict):
            known=model.get('vision_token_bounds',{}).get(part['image_url'].get('detail','auto'))
            if known is None:unknown_images=True
            else:image_tokens+=known
            part['image_url']['url']='[image input]';images+=1
    text_bound=len(canonical(framed).encode())+1024
    # All images and text share ONE model input context. Without a reviewed
    # image formula, reserve that entire window once, never once per image.
    # Keep oversized text explicit so it can still be rejected before HTTP.
    if unknown_images:return max(text_bound+image_tokens,model['context_length']),images
    return text_bound+image_tokens,images


def parse_decision(payload, questions, model='gpt-6-luna'):
    if not isinstance(payload, dict) or payload.get('model') != model:
        raise ContractError('Unexpected Decisions model')
    answers = payload.get('answers')
    if not isinstance(answers, list) or len(answers) != len(questions):
        raise ContractError('Missing Decisions answers')
    result = {}
    for question, answer in zip(questions, answers):
        name = question.get('name')
        if not name or name in result or not isinstance(answer, dict) or answer.get('name') != name:
            raise ContractError('Unmatched Decisions answer name or order')
        if answer.get('type') == 'refusal':
            result[name] = answer
            continue
        def typed_number(value,name,low=0,high=1):
            if type(value) not in (int,float): raise ContractError('Expected a numeric Decisions '+name)
            return number(value,name,low,high)
        kind = question['type']
        if answer.get('type') != kind:
            raise ContractError('Unexpected Decisions answer type')
        if kind == 'predicate':
            typed_number(answer.get('probability'), 'probability', 0, 1)
        else:
            typed_number(answer.get('confidence'), 'confidence', 0, 1)
            probabilities = answer.get('probabilities')
            options = [item['value'] for item in question['choices']] if kind == 'choice' else list(range(len(question['levels'])))
            if not isinstance(probabilities, list) or len(probabilities) != len(options):
                raise ContractError('Incomplete probability distribution')
            values = [item.get('value') for item in probabilities]
            if [(type(v), v) for v in values] != [(type(v), v) for v in options]:
                raise ContractError('Unmatched probability options')
            ps = [typed_number(item.get('probability'), 'probability', 0, 1) for item in probabilities]
            if not math.isclose(sum(ps), 1, abs_tol=.002):
                raise ContractError('Invalid probability mass')
            if kind == 'choice':
                if (type(answer.get('choice')), answer.get('choice')) not in [(type(v), v) for v in options]:
                    raise ContractError('Choice outside allowed actions')
            elif kind == 'score':
                score = typed_number(answer.get('score'), 'score', 0, len(options) - 1)
                if any(item.get('label') != question['levels'][i]['label'] for i, item in enumerate(probabilities)):
                    raise ContractError('Unmatched score levels')
                if not math.isclose(score, sum(i * p for i, p in enumerate(ps)), abs_tol=.002):
                    raise ContractError('Score disagrees with its distribution')
            else:
                raise ContractError('Unsupported Decisions question')
        result[name] = answer
    return result


def parse_openrouter_decision(payload,questions,model):
    if not isinstance(payload,dict) or payload.get('model')!=model:raise ContractError('Unexpected Decisions model')
    raw=payload.get('answers')
    if not isinstance(raw,dict) or set(raw)!={q['name'] for q in questions}:raise ContractError('Missing Decisions answers')
    result={}
    for q in questions:
        a=raw[q['name']]
        if not isinstance(a,dict):raise ContractError('Invalid Decisions answer')
        item={'name':q['name'],'type':q['type']}
        if a.get('type')=='refusal':result[q['name']]={'name':q['name'],'type':'refusal'};continue
        if q['type']=='predicate':
            if a.get('type')!='noul' or type(a.get('noul')) not in (int,float):raise ContractError('Unexpected Decisions predicate')
            item['probability']=number(a['noul'],'probability',0,1)
        else:
            if a.get('type')!=q['type']:raise ContractError('Unexpected Decisions answer type')
            if a.get('confidence') is not None:
                if type(a['confidence']) not in (int,float):raise ContractError('Expected numeric confidence')
                item['confidence']=number(a['confidence'],'confidence',0,1)
            probs=a.get('probabilities')
            if probs is not None:
                if not isinstance(probs,dict) or any(type(v) not in (int,float) for v in probs.values()):raise ContractError('Expected numeric probabilities')
                ps=[number(v,'probability',0,1) for v in probs.values()]
                if not math.isclose(sum(ps),1,abs_tol=.002):raise ContractError('Invalid probability mass')
            if q['type']=='choice':
                options=[c['value'] for c in q['choices']]
                keys=[str(v).lower() if isinstance(v,bool) else v for v in options]
                if a.get('choice') not in keys:raise ContractError('Choice outside allowed actions')
                item['choice']=options[keys.index(a['choice'])]
                # OpenRouter declares these fields optional; never invent confidence.
                if probs is not None:
                    if set(probs)!=set(keys):raise ContractError('Unmatched Decisions choices')
                    item['probabilities']=[{'value':v,'probability':probs[k]} for v,k in zip(options,keys)]
            elif q['type']=='score':
                # A complete distribution identifies the provider's ordinal scale.
                if probs is None:raise ContractError('Missing Decisions score distribution')
                count=len(q['levels']);offset=0 if set(probs)=={str(i) for i in range(count)} else 1
                if set(probs)!={str(i+offset) for i in range(count)} or type(a.get('score')) not in (int,float):raise ContractError('Unmatched score levels')
                item['score']=number(a['score']-offset,'score',0,count-1)
                item['probabilities']=[{'value':i,'label':q['levels'][i]['label'],'probability':probs[str(i+offset)]} for i in range(count)]
                if not math.isclose(item['score'],sum(i*probs[str(i+offset)] for i in range(count)),abs_tol=.002):raise ContractError('Score disagrees with its distribution')
            else:raise ContractError('Unsupported Decisions question')
        result[q['name']]=item
    return result


class Ledger:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY, logical_key TEXT UNIQUE NOT NULL, campaign TEXT NOT NULL,
                run TEXT NOT NULL, account TEXT NOT NULL, created REAL NOT NULL,
                reserved REAL NOT NULL, cost REAL, cost_status TEXT NOT NULL,
                status TEXT NOT NULL, request_hash TEXT NOT NULL, request_id TEXT NOT NULL,
                response_id TEXT, model TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER,
                elapsed REAL, error TEXT)''')

    def rows(self, campaign=None, run=None, account=None):
        clauses, params = [], []
        for key, value in (('campaign', campaign), ('run', run), ('account', account)):
            if value is not None:
                clauses.append(key + '=?'); params.append(value)
        with self.store.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM calls' + (' WHERE ' + ' AND '.join(clauses) if clauses else '') + ' ORDER BY created,id', params)]

    def retryable_failure(self, call):
        call = dict(call)
        if call['status'] == 'transport_error':
            return call['response_id'] is None
        if call['status'] not in ('received', 'http_error') or not call['response_id']:
            return False
        try:
            payload = json.loads(self.store.read_blob(call['response_id']))
        except (ValueError, TypeError):
            return False
        error = payload.get('error')
        transient_codes = (408, 429, 500, 502, 503, 504, 520)
        choices = payload.get('choices')
        if payload.get('output'):
            return False
        if not choices:
            return isinstance(error, dict) and error.get('code') in transient_codes
        if not isinstance(choices, list) or len(choices) != 1:
            return False
        choice = choices[0]
        if not isinstance(choice, dict):
            return False
        message = choice.get('message') or {}
        error = choice.get('error')
        details = message.get('reasoning_details') if isinstance(message, dict) else None
        encrypted_only = (isinstance(details, list) and bool(details)
                          and all(isinstance(item, dict) and item.get('type') == 'reasoning.encrypted'
                                  for item in details)
                          and payload.get('usage', {}).get('completion_tokens') == 0)
        metadata = {'role', 'reasoning_details'} if encrypted_only else {'role'}
        return (choice.get('finish_reason') == 'error'
                and isinstance(error, dict) and error.get('code') in transient_codes
                and isinstance(message, dict)
                and not any(value for key, value in message.items() if key not in metadata))

    def authorize_transport_retry(self, call_id, reconciliation_id, reference):
        """Authorize one identical retry after reconciling a failed provider request."""
        reconciliation = self.store.get(reconciliation_id)
        if reconciliation['kind'] != 'call_reconciliation' or not reference.strip():
            raise ContractError('Retry requires a reconciliation receipt and recovery reference')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            call = db.execute('SELECT * FROM calls WHERE id=?', (call_id,)).fetchone()
            if (call is None or not self.retryable_failure(call)
                    or call['cost_status'] != 'reconciled'
                    or reconciliation['campaign'] != call['campaign']
                    or reconciliation['data']['call_id'] != call_id
                    or reconciliation['data']['cost_usd'] != call['cost']):
                raise ContractError('Retry requires a reconciled transport failure without a response')
            data = {'schema': 'a11yharness/1', 'call_id': call_id,
                    'reconciliation_id': reconciliation_id, 'reference': reference,
                    'request_hash': call['request_hash'], 'logical_key': call['logical_key'],
                    'retry_key': call['logical_key'] + ':reconciled-transport-retry:1',
                    'run': call['run'], 'account': call['account'], 'model': call['model']}
            if call['response_id']:
                data['failure_response_id'] = call['response_id']
            ident = 'call-retry-' + call_id
            existing = db.execute('SELECT * FROM records WHERE id=?', (ident,)).fetchone()
            if existing:
                if self.store.unpack(existing)['data'] != data:
                    raise Conflict('An authorized retry cannot change its billing basis')
            else:
                db.execute('INSERT INTO records VALUES (?,?,?,?,?,?)',
                           (ident, 'call_retry_authorization', call['campaign'],
                            canonical(data), digest(data), time.time()))
        return self.store.get(ident)

    def begin(self, campaign, run, account, key, request, model, limits, campaign_limit, group=None):
        request_hash = digest(request)
        input_bound,images=input_token_bound(request,model)
        output_bound = int(request.get('max_tokens') or request.get('options', {}).get('num_predict') or 0)
        # A byte upper bound safely reserves money, but does not establish that
        # a prompt exceeds a tokenizer's context. Only explicit no-compression
        # OpenRouter chat requests delegate token-context admission to the native
        # provider; all monetary/call quotas still use the unchanged upper bound.
        native_context = (model.get('provider') == 'openrouter'
                          and isinstance(request.get('messages'), list)
                          and request.get('plugins') == [{'id':'context-compression','enabled':False}])
        if output_bound > model['context_length'] or (not native_context and
                (input_bound > model['context_length'] or (not images and input_bound + output_bound > model['context_length']))):
            raise BudgetStop('Request exceeds the declared model context bound; no truncation was performed')
        from model_catalog_metadata import pricing_rates
        input_rate, output_rate = pricing_rates(model, input_bound)
        reserve = (input_bound * input_rate + output_bound * output_rate) / 1000000
        replacement_call_id = None
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM calls WHERE logical_key=?', (key,)).fetchone()
            if existing:
                if existing['status'] == 'dispatching' or existing['cost_status'] == 'unknown':
                    raise UncertainCall('Provider consumption is unresolved; automatic replay is forbidden')
                if existing['request_hash'] != request_hash:
                    raise Conflict('A checkpointed provider request changed')
                authorization = db.execute('SELECT * FROM records WHERE id=?',
                                           ('call-retry-' + existing['id'],)).fetchone()
                if not authorization:
                    return dict(existing), False
                authorization = self.store.unpack(authorization)
                retry = authorization['data']
                reconciliation = db.execute('SELECT * FROM records WHERE id=?',
                                            (retry['reconciliation_id'],)).fetchone()
                reconciliation = self.store.unpack(reconciliation) if reconciliation else None
                if (authorization['kind'] != 'call_retry_authorization'
                        or authorization['campaign'] != campaign
                        or (existing['campaign'], existing['run'], existing['account'], existing['model'])
                        != (campaign, run, account, model['model'])
                        or retry['request_hash'] != request_hash
                        or not self.retryable_failure(existing)
                        or retry.get('failure_response_id') != existing['response_id']
                        or existing['cost_status'] != 'reconciled'
                        or not reconciliation or reconciliation['kind'] != 'call_reconciliation'
                        or reconciliation['data']['call_id'] != existing['id']
                        or reconciliation['data']['cost_usd'] != existing['cost']):
                    raise ContractError('Authorized retry cannot change the request or execution scope')
                replacement_call_id = existing['id']
                key = retry['retry_key']
                retried = db.execute('SELECT * FROM calls WHERE logical_key=?', (key,)).fetchone()
                if retried:
                    if retried['status'] == 'dispatching' or retried['cost_status'] == 'unknown':
                        raise UncertainCall('Retry consumption is unresolved; another dispatch is forbidden')
                    if retried['request_hash'] != request_hash:
                        raise Conflict('The authorized retry request changed')
                    return dict(retried), False
            if reserve > limits.get('max_call_cost_usd', math.inf) + 1e-12:
                raise BudgetStop('Request reservation exceeds the per-call cost limit; no HTTP request sent')
            if group:
                from .preparation import compatible_groups
                campaigns = {row['id']: json.loads(row['payload']).get('budget_group')
                             for row in db.execute("SELECT id,payload FROM records WHERE kind IN ('campaign','billing_archive')")}
                campaigns = {key: value for key, value in campaigns.items() if value and value['id'] == group['id']}
                if campaign not in campaigns or any(not compatible_groups(previous, group) for previous in campaigns.values()):
                    raise ContractError('Shared budget group limits cannot change between campaigns')
                grouped = [dict(row) for row in db.execute('SELECT * FROM calls') if row['campaign'] in campaigns]
                # Unknown calls keep their full reservation. Their own campaign
                # and key remain blocked, while independent work stays bounded.
                amount = lambda row: row['cost'] if row['cost'] is not None else row['reserved']
                staged = [row for row in grouped if campaigns[row['campaign']]['stage'] == group['stage']]
                from .shared_budget import effective_group
                amendments = [self.store.unpack(row) for row in db.execute(
                    "SELECT * FROM records WHERE kind='shared_budget_amendment' ORDER BY created,id")]
                effective = effective_group(group, amendments)
                if sum(map(amount, grouped)) + reserve > effective['total_usd'] + 1e-12:
                    raise BudgetStop('Shared total cost limit reached')
                if sum(map(amount, staged)) + reserve > effective['stage_limits'][group['stage']] + 1e-12:
                    raise BudgetStop('Shared stage cost limit reached')
            all_calls = [dict(row) for row in db.execute('SELECT * FROM calls WHERE campaign=?', (campaign,))]
            if any(row['cost_status'] == 'unknown' or row['status'] == 'dispatching' for row in all_calls):
                raise UncertainCall('A previous campaign call has unresolved consumption')
            scoped = [row for row in all_calls if row['run'] == run and (row['account'] == account if account=='repair' else row['account'] in ('review','learning'))]
            # One receipt-authorized retransmission replaces its failed logical
            # request. It cannot open a new call slot or discard earlier charges.
            quota_calls = [row for row in scoped if row['id'] != replacement_call_id]
            if len(quota_calls) >= limits['max_calls']:
                raise BudgetStop('Provider call limit reached')
            def amount(row):
                return row['cost'] if row['cost'] is not None else row['reserved']
            if sum(map(amount, scoped)) + reserve > limits['max_cost_usd'] + 1e-12:
                raise BudgetStop('Insufficient account budget for a bounded request')
            if sum(map(amount, all_calls)) + reserve > campaign_limit + 1e-12:
                raise BudgetStop('Campaign cost limit reached')
            if scoped and time.time() - min(row['created'] for row in scoped) >= limits['max_seconds']:
                raise BudgetStop('Provider account time limit reached')
            ident = uuid.uuid4().hex
            request_id = uuid.uuid4().hex
            data = {'schema': 'a11yharness/1', 'call_id': ident, 'model': model,
                    'request': request, 'logical_key': key, 'account': account,
                    'reservation':{'input_token_bound':input_bound,'output_token_bound':output_bound,
                        'input_bound_scope':'UTF-8 byte upper bound and declared image allowance, not a native token count',
                        'context_validation':'provider-native-tokenizer-no-compression' if native_context else 'conservative-local-bound',
                        'input_usd_per_million':input_rate,'output_usd_per_million':output_rate,'usd':reserve}}
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?)',
                       (request_id, 'call_request', campaign, canonical(data), digest(data), time.time()))
            db.execute('INSERT INTO calls(id,logical_key,campaign,run,account,created,reserved,cost_status,status,request_hash,request_id,model) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (ident, key, campaign, run, account, time.time(), reserve, 'reserved', 'dispatching', request_hash, request_id, model['model']))
            return dict(db.execute('SELECT * FROM calls WHERE id=?', (ident,)).fetchone()), True

    def received(self, call, raw, model, elapsed, status_code):
        response = self.store.blob(raw, 'provider_response', call['campaign'], 'application/json')
        usage, actual_model, cost, cost_status = {}, None, None, 'unknown'
        try:
            envelope = json.loads(raw)
            usage = envelope.get('usage') or {}
            actual_model = envelope.get('model')
            input_tokens = usage.get('input_tokens', usage.get('prompt_tokens', envelope.get('prompt_eval_count')))
            output_tokens = usage.get('output_tokens', usage.get('completion_tokens', envelope.get('eval_count')))
            if input_tokens is not None and output_tokens is not None:
                input_tokens = number(input_tokens, 'input tokens', 0, None, True)
                output_tokens = number(output_tokens, 'output tokens', 0, None, True)
                reported = usage.get('cost')
                if reported is not None:
                    cost, cost_status = number(reported, 'reported cost', 0), 'provider_reported'
                else:
                    from model_catalog_metadata import pricing_rates
                    input_rate, output_rate = pricing_rates(model,input_tokens)
                    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1000000
                    cost_status = 'local' if model['provider'] == 'ollama' else 'estimated'
            else:
                input_tokens, output_tokens = None, None
        except (ValueError, TypeError, AttributeError):
            input_tokens, output_tokens = None, None
        with self.store.connect() as db:
            db.execute('UPDATE calls SET response_id=?,status=?,cost=?,cost_status=?,input_tokens=?,output_tokens=?,elapsed=? WHERE id=?',
                       (response['id'], 'received' if status_code < 400 else 'http_error', cost, cost_status, input_tokens, output_tokens, elapsed, call['id']))
        self.store.append('call_receipt', {'call_id': call['id'], 'response_id': response['id'],
                           'http_status': status_code, 'returned_model': actual_model, 'usage': usage,
                           'cost_usd': cost, 'cost_status': cost_status, 'elapsed_seconds': elapsed,
                           'pricing_source': model['pricing_source']}, call['campaign'])
        return response['id']

    def failed(self, call, error, elapsed):
        with self.store.connect() as db:
            db.execute('UPDATE calls SET status=?,cost_status=?,elapsed=?,error=? WHERE id=?',
                       ('transport_error', 'unknown', elapsed, type(error).__name__, call['id']))
        self.store.append('call_error', {'call_id': call['id'], 'error_type': type(error).__name__,
                           'consumption': 'unknown'}, call['campaign'])

    def reconcile(self, call_id, cost, reference):
        cost = number(cost, 'reconciled charge', 0)
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError('A billing or provider reference is required')
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM calls WHERE id=?', (call_id,)).fetchone()
            if row is None:
                raise KeyError(call_id)
            db.execute('UPDATE calls SET cost=?,cost_status=?,status=CASE WHEN status="dispatching" THEN "interrupted" ELSE status END WHERE id=?',
                       (cost, 'reconciled', call_id))
        return self.store.append('call_reconciliation', {'call_id': call_id, 'cost_usd': cost, 'reference': reference}, row['campaign'])

    def record_unavailable_completion(self, call_id, metadata, content_lookup, reference):
        """Close known billing without inventing a response or authorizing a retry."""
        with self.store.connect() as db:
            call = dict(db.execute('SELECT * FROM calls WHERE id=?', (call_id,)).fetchone())
        headers = self.store.list('provider_response_headers', call['campaign'])
        if (call['status'] != 'transport_error' or call['response_id'] is not None
                or call['cost_status'] != 'reconciled'
                or abs(call['cost'] - metadata['total_cost']) > 1e-10
                or not any(r['data'].get('call_id') == call_id and
                           r['data'].get('generation_id') == metadata['id'] for r in headers)
                or content_lookup.get('http_status') != 404 or not reference.strip()):
            raise ContractError('Unavailable completion requires exact reconciled provider evidence')
        receipt = self.store.append('provider_completion_unavailable', {
            'call_id': call_id, 'provider_metadata': metadata,
            'content_lookup': content_lookup, 'reference': reference,
            'response_available': False, 'generation_repeated': False,
        }, call['campaign'])
        with self.store.connect() as db:
            db.execute('UPDATE calls SET input_tokens=?,output_tokens=? WHERE id=?',
                       (metadata.get('native_tokens_prompt'), metadata.get('native_tokens_completion'), call_id))
        return receipt


class Providers:
    def __init__(self, store, manifest, campaign, settings, session=requests):
        self.store, self.manifest, self.campaign = store, manifest, campaign
        self.settings, self.session, self.ledger = settings, session, Ledger(store)
        self.completion_stage = None

    def read_response(self, response, call):
        """Keep incomplete transport bytes as evidence, never as a model result."""
        if not hasattr(response, 'iter_content'):
            return response.text
        chunks = []
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    chunks.append(chunk)
        except requests.RequestException:
            partial = self.store.blob(b''.join(chunks), 'provider_partial_transport',
                                      call['campaign'], 'application/octet-stream')
            self.store.append('provider_partial_response', {
                'call_id':call['id'], 'artifact_id':partial['id'],
                'complete':False, 'response_interpreted':False,
            }, call['campaign'])
            raise
        return b''.join(chunks).decode(response.encoding or 'utf-8', errors='replace')

    def begin_completion_stage(self, stage, run=None):
        from .time_policy import STAGES, finishes_stage
        if stage not in STAGES:
            raise ContractError('Invalid completion stage')
        self.completion_stage = stage
        if finishes_stage(self.manifest, stage):
            self.store.append('time_stage', {'stage':stage, 'run_id':run,
                'policy':self.manifest['time_policy'], 'started':time.time(),
                'iteration_start_budget_seconds':self.manifest['repair_budget']['max_seconds']}, self.campaign)

    @contextmanager
    def complete_stage(self, stage, run=None):
        previous = self.completion_stage
        self.begin_completion_stage(stage, run)
        try:
            yield
        finally:
            self.completion_stage = previous

    def dispatch(self, run, account, key, model, body, endpoint, credential=None, parser=None):
        # A logical key can be shared by independent campaigns using the same
        # source evidence. Let its active owner finish, then reuse its receipt.
        # The ledger still rejects an orphaned or genuinely unknown charge.
        import fcntl

        locks = self.store.root / 'call-locks'
        locks.mkdir(mode=0o700, exist_ok=True)
        with (locks / (digest(key) + '.lock')).open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            return self._dispatch(run, account, key, model, body, endpoint, credential, parser)

    def _dispatch(self, run, account, key, model, body, endpoint, credential=None, parser=None):
        body = bind_provider_route(body, model)
        # Shared boundary covers the SQL generation adapter as well as chat().
        # Persist exactly the payload whose compression policy is enforced.
        if model.get('provider') == 'openrouter' and isinstance(body.get('messages'), list):
            body = copy.deepcopy(body)
            body['plugins'] = [{'id':'context-compression','enabled':False}]
        limits = self.manifest['repair_budget'] if account == 'repair' else self.manifest['review_budget']
        from .time_policy import effective_limits, finishes_stage
        limits = effective_limits(limits, self.manifest, self.completion_stage)
        if model['provider'] != 'ollama' and not credential:
            raise ContractError('Configure the selected provider credential on the server')
        from .pausing import check
        check(self.store,self.campaign)
        if finishes_stage(self.manifest,self.completion_stage) and getattr(self,'lease_owner',None):
            if not self.store.claim(self.campaign,self.lease_owner,900):
                raise Conflict('Campaign lease was lost')
        call, fresh = self.ledger.begin(
            self.campaign, run, account, key, body, model, limits,
            self.manifest['campaign_cost_limit'], self.manifest.get('budget_group'))
        self.last_call = call
        if fresh:
            started = time.monotonic()
            try:
                headers = {'Content-Type': 'application/json'}
                if credential:
                    headers['Authorization'] = 'Bearer ' + credential
                scoped=[r for r in self.ledger.rows(self.campaign,run) if (r['account']==account if account=='repair' else r['account'] in ('review','learning'))]
                remaining=limits['max_seconds']-(time.time()-min(r['created'] for r in scoped))
                if getattr(self,'repair_deadline',None) and not finishes_stage(self.manifest,self.completion_stage):remaining=min(remaining,self.repair_deadline-time.time())
                if remaining<=0:
                    self.ledger.reconcile(call['id'],0,'Deterministic deadline elapsed before dispatch; no HTTP request sent')
                    raise BudgetStop('Account deadline elapsed before dispatch')
                response = self.session.post(endpoint, json=body, headers=headers,
                                             timeout=min(180,remaining), stream=True)
                generation_id = getattr(response, 'headers', {}).get('X-Generation-Id')
                if isinstance(generation_id, str) and re.fullmatch(r'gen-[A-Za-z0-9_-]{1,160}', generation_id):
                    self.store.append('provider_response_headers', {
                        'call_id': call['id'], 'generation_id': generation_id,
                        'http_status': response.status_code,
                    }, self.campaign)
                raw = self.read_response(response, call)
                response_id = self.ledger.received(call, raw, model, time.monotonic() - started, response.status_code)
            except requests.RequestException as error:
                self.ledger.failed(call, error, time.monotonic() - started)
                raise UncertainCall('Transport failed; consumption must be reconciled') from error
            if time.monotonic()-started>remaining:raise BudgetStop('Provider exceeded its recorded deadline; response and charge retained')
            if response.status_code >= 400:
                raise ContractError('Provider returned HTTP ' + str(response.status_code))
        else:
            if call['status'] == 'http_error':
                raise ContractError('Checkpointed provider HTTP error; no automatic retry')
            if not call['response_id']:
                raise ContractError('The checkpointed call ended without a reusable response')
            response_id = call['response_id']
        payload = json.loads(self.store.read_blob(response_id))
        if isinstance(payload.get('error'), dict):
            raise ContractError('Provider error ' + str(payload['error'].get('code', 'unknown'))
                                + '; response and billing evidence retained')
        if payload.get('model') != model.get('response_model', model['model']):
            raise ContractError('Returned model differs from the frozen requested identity')
        return parser(payload) if parser else payload

    def chat(self, run, account, key, model, prompt, json_mode=True, image_parts=(), response_schema=None):
        limits = self.manifest['repair_budget'] if account == 'repair' else self.manifest['review_budget']
        content = prompt
        if image_parts:
            if not model.get('vision'):
                raise ContractError('Selected judge lacks the declared image capability')
            content = [{'type': 'text', 'text': prompt}, *image_parts]
        body = {'model': model['model'], 'messages': [{'role': 'user', 'content': content}],
                'max_tokens': limits['max_output_tokens'], 'stream': False,
                'provider': {'allow_fallbacks':False,'require_parameters':True},
                'plugins':[{'id':'context-compression','enabled':False}]}
        openai_reasoning = (model['model'].startswith('openai/')
                            and model.get('reasoning_effort') != 'none')
        if model.get('temperature_supported', False) and not openai_reasoning:
            body['temperature'] = .05
        if model.get('reasoning_effort'):
            body['reasoning'] = {'effort': model['reasoning_effort']}
        if json_mode:
            body['response_format'] = {'type': 'json_object'}
            if response_schema is not None:
                if 'structured_outputs' not in model.get('supported_parameters', []):
                    raise ContractError('The frozen model does not declare structured output support')
                body['response_format'] = {'type':'json_schema','json_schema':{
                    'name':'a11yharness_visual_evidence','strict':True,'schema':response_schema}}
        if model['provider'] == 'ollama':
            message={'role':'user','content':prompt}
            if image_parts:
                images=[]
                for part in image_parts:
                    value=part.get('image_url',{}).get('url','')
                    if not value.startswith('data:image/') or ';base64,' not in value: raise ContractError('Local judges require acquired inline images')
                    images.append(value.split(';base64,',1)[1])
                message['images']=images
            body = {'model': model['model'], 'messages': [message], 'stream': False,'truncate':False,'shift':False,
                    'options': {'num_predict': limits['max_output_tokens'],'num_ctx':model['context_length']}}
            if model.get('temperature_supported',False):body['options']['temperature']=.05
            if model.get('reasoning_effort'):body['think']=False if model['reasoning_effort']=='none' else model['reasoning_effort']
            if json_mode:
                body['format'] = 'json'
            base=self.settings['ollama_base_url'].rstrip('/')
            if base.endswith('/v1'):base=base[:-3]
            endpoint = base + '/api/chat'
            envelope = self.dispatch(run, account, key, model, body, endpoint)
            if envelope.get('done') is not True or envelope.get('done_reason')=='length' or not isinstance(envelope.get('message',{}).get('content'),str):
                raise ContractError('Local output is missing, incomplete or truncated')
            value = envelope['message']['content']
            return canonical(decode_json(value)) if json_mode else value
        endpoint = self.settings['openrouter_base_url'].rstrip('/') + '/chat/completions'
        envelope = self.dispatch(run, account, key, model, body, endpoint,
                                self.settings.get('openrouter_api_key'))
        choices = envelope.get('choices')
        if not choices or choices[0].get('finish_reason') in ('length', 'content_filter'):
            raise ContractError('Provider output is missing, truncated or filtered')
        value = choices[0].get('message', {}).get('content')
        if not isinstance(value, str):
            raise ContractError('Expected textual model output')
        return canonical(decode_json(value)) if json_mode else value

    def decisions(self, run, account, key, evidence, questions, *, model=None, image_parts=()):
        if not isinstance(questions,list) or any(not isinstance(q,dict) for q in questions) or not isinstance(evidence,str):
            raise ContractError('Decisions requires text evidence and typed questions')
        names = [q.get('name') for q in questions]
        if not questions or any(not isinstance(n,str) or not n for n in names) or len(set(names)) != len(names):
            raise ContractError('Decisions questions need distinct names')
        for q in questions:
            if not isinstance(q.get('instructions'),str) or not q['instructions'].strip():raise ContractError('Decisions requires the official instructions field')
            if set(q)-{'type','name','instructions','choices','levels'}:raise ContractError('Unknown Decisions question field')
            if q.get('type') == 'choice':
                choices = q.get('choices') or []
                if not isinstance(choices,list) or any(not isinstance(v,dict) or type(v.get('value')) not in (str,bool) for v in choices):
                    raise ContractError('Decisions choices must be strings or booleans')
                values = [(type(v.get('value')).__name__, v.get('value')) for v in choices]
                if not 2 <= len(choices) <= 255 or len(set(values)) != len(values):
                    raise ContractError('Decisions needs 2–255 unique choices')
            elif q.get('type')=='score':
                levels=q.get('levels')
                if not isinstance(levels,list) or len(levels)<2 or any(not isinstance(l,dict) or not isinstance(l.get('label'),str) or not l['label'] for l in levels):
                    raise ContractError('Decisions scores need distinct labeled ordered levels')
                if len({l['label'] for l in levels})!=len(levels):raise ContractError('Decisions score levels must be unique')
            elif q.get('type') not in ('predicate', 'score'):
                raise ContractError('Unsupported Decisions question')
        from .decision_models import snapshot
        model=snapshot(model or self.manifest.get('decision_model'))
        if len(questions)>200:raise ContractError('Use at most 200 independent decision questions')
        mapped={}
        for q in questions:
            item={'type':'noul' if q['type']=='predicate' else q['type'],'instructions':q['instructions']}
            if q['type']=='choice':
                item['criteria']={str(c['value']).lower() if isinstance(c['value'],bool) else c['value']:c.get('description',str(c['value'])) for c in q['choices']}
                if len(item['criteria'])!=len(q['choices']):raise ContractError('Ambiguous decision choice keys')
            elif q['type']=='score':item['criteria']=[v.get('description') or v['label'] for v in q['levels']]
            mapped[q['name']]=item
        state=evidence
        if image_parts:
            if not model.get('vision'):raise ContractError('Selected Decisions model lacks image capability')
            if len(image_parts)>4:raise ContractError('Use at most four reviewed images per Decisions request')
            for part in image_parts:
                if not isinstance(part,dict) or set(part)!={'type','image_url'} or part['type']!='image_url':
                    raise ContractError('Invalid Decisions image part')
                image=part['image_url']
                if not isinstance(image,dict) or set(image)-{'url','detail'} or image.get('detail','auto') not in ('auto','low','high'):
                    raise ContractError('Invalid Decisions image fields')
                uri=image.get('url')
                if not isinstance(uri,str) or not re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}',uri):
                    raise ContractError('Decisions requires acquired inline PNG, JPEG or WebP images')
                try:base64.b64decode(uri.split(',',1)[1],validate=True)
                except ValueError as error:raise ContractError('Invalid Decisions image encoding') from error
            state=[evidence,*image_parts]
        body={'model':model['model'],'state':state,'questions':mapped,'provider':{'allow_fallbacks':False}}
        endpoint=re.sub(r'/api/v1/?$','',self.settings['openrouter_base_url'].rstrip('/'))+'/api/alpha/decisions'
        return self.dispatch(run,account,key,model,body,endpoint,self.settings.get('openrouter_api_key'),
                             lambda p:parse_openrouter_decision(p,questions,model.get('response_model',model['model'])))
