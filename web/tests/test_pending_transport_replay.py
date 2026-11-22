"""Pending advice restores byte-identical inputs without fabricating a response."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from remediation_agent_runtime import AgentRuntime
from remediation_call_evidence import RecordedModelCalls
from harness.providers import UncertainCall


class PendingReplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.caller = Mock(side_effect=UncertainCall('transport interrupted'))
        self.identity = lambda completed=False: 'owned-logical-call'
        prefix = 'You are the accessibility diagnosis agent BEFORE localized patch generation.\n'
        self.original = prefix + json.dumps({'feedback': json.dumps({'axe': 4, 'links': ['a', 'b']}), 'context': 'same'})
        self.reordered = prefix + json.dumps({'context': 'same', 'feedback': json.dumps({'links': ['a', 'b'], 'axe': 4})})
        self.messages = [{'role': 'user', 'content': [{'type': 'text', 'text': self.original},
                         {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,c2FtZQ=='}}]}]
        self.runtime = AgentRuntime(2, 42, 1, 1800)
        recorded = RecordedModelCalls(self.directory.name, self.runtime, self.caller,
                                      call_identity=self.identity)
        with self.assertRaises(RuntimeError):
            recorded({}, 'explicit/model', self.original, messages=self.messages,
                     task_name='repair-diagnostician')
        self.caller.side_effect = None
        self.caller.return_value = ('actual new reply', 12, 3, .001, .5, 'explicit/model')

    def resume(self, prompt=None, messages=None, identity=True, **kwargs):
        prompt = self.reordered if prompt is None else prompt
        if messages is None:
            messages = json.loads(json.dumps(self.messages))
            messages[0]['content'][0]['text'] = prompt
        recorded = RecordedModelCalls(self.directory.name, self.runtime, self.caller,
            resume_existing=True, call_identity=self.identity if identity else None)
        result = recorded({}, 'explicit/model', prompt, messages=messages,
                          task_name='repair-diagnostician', **kwargs)
        return recorded, result

    def test_restores_exact_failed_prompt_and_images_but_makes_one_real_call(self):
        recorded, result = self.resume()
        self.assertEqual(self.caller.call_count, 2)
        self.assertEqual(self.caller.call_args.args[2], self.original)
        self.assertEqual(self.caller.call_args.args[7], self.messages)
        self.assertEqual(result[0], 'actual new reply')
        self.assertEqual([r['status'] for r in recorded.records], ['transport_failed', 'returned'])
        self.assertEqual(recorded.records[-1]['prompt'], self.original)
        self.assertNotIn('response', recorded.records[0])

    def test_changed_evidence_is_never_restored(self):
        changed = self.reordered.replace('4', '5')
        self.resume(changed)
        self.assertEqual(self.caller.call_args.args[2], changed)

    def test_http_error_restores_original_serialization_before_ledger_validation(self):
        path = Path(self.directory.name)/'model-call-evidence.json'
        document = json.loads(path.read_text())
        document['calls'][0].update(error_type='ContractError')
        path.write_text(json.dumps(document))
        self.resume()
        self.assertEqual(self.caller.call_args.args[2], self.original)
        self.assertEqual(self.caller.call_args.args[7], self.messages)

    def test_http_error_owned_by_another_call_is_not_restored(self):
        path = Path(self.directory.name)/'model-call-evidence.json'
        document = json.loads(path.read_text())
        document['calls'][0].update(error_type='ContractError', pending_call_id='other-call')
        path.write_text(json.dumps(document))
        self.resume()
        self.assertEqual(self.caller.call_args.args[2], self.reordered)

    def test_owned_incomplete_provider_error_restores_only_original_serialization(self):
        path=Path(self.directory.name)/'model-call-evidence.json'
        document=json.loads(path.read_text())
        document['calls'][0].update(status='output_incomplete', error_type='ModelOutputIncomplete',
                                   finish_reason='error', call_id='owned-logical-call')
        path.write_text(json.dumps(document))
        self.resume()
        self.assertEqual(self.caller.call_args.args[2],self.original)
        self.assertEqual(self.caller.call_args.args[7],self.messages)

    def test_incomplete_output_from_another_owned_call_is_not_restored(self):
        path=Path(self.directory.name)/'model-call-evidence.json'
        document=json.loads(path.read_text())
        document['calls'][0].update(status='output_incomplete', error_type='ModelOutputIncomplete',
                                   finish_reason='error', call_id='other-call')
        path.write_text(json.dumps(document))
        self.resume()
        self.assertEqual(self.caller.call_args.args[2],self.reordered)

    def test_changed_image_is_never_restored(self):
        messages = json.loads(json.dumps(self.messages))
        messages[0]['content'][0]['text'] = self.reordered
        messages[0]['content'][1]['image_url']['url'] += 'different'
        self.resume(messages=messages)
        self.assertEqual(self.caller.call_args.args[2], self.reordered)
        self.assertEqual(self.caller.call_args.args[7], messages)

    def test_without_owned_call_identity_no_pending_restoration(self):
        self.resume(identity=False)
        self.assertEqual(self.caller.call_args.args[2], self.reordered)

    def test_changed_output_allowance_is_not_restored(self):
        self.resume(output_token_limit=256)
        self.assertEqual(self.caller.call_args.args[2], self.reordered)
        self.assertEqual(self.caller.call_args.args[9], 256)

    def test_failed_retry_preserves_both_failures_and_does_not_invent_usage(self):
        self.caller.side_effect = RuntimeError('billing still unresolved')
        with self.assertRaisesRegex(RuntimeError, 'billing still unresolved'):
            self.resume()
        document = json.loads((Path(self.directory.name)/'model-call-evidence.json').read_text())
        self.assertEqual([r['status'] for r in document['calls']], ['transport_failed'] * 2)
        self.assertTrue(all('response' not in r and 'cost_usd' not in r for r in document['calls']))

    def test_later_local_hash_rejection_does_not_shadow_original_pending_inputs(self):
        path = Path(self.directory.name)/'model-call-evidence.json'
        document = json.loads(path.read_text())
        rejected = dict(document['calls'][0], call_number=2, error_type='Conflict',
                        prompt=self.reordered)
        rejected['messages'] = json.loads(json.dumps(self.messages))
        rejected['messages'][0]['content'][0]['text'] = self.reordered
        document['calls'].append(rejected)
        path.write_text(json.dumps(document))
        self.resume()
        self.assertEqual(self.caller.call_args.args[2], self.original)
        self.assertEqual(self.caller.call_args.args[7], self.messages)


if __name__ == '__main__':
    unittest.main()
