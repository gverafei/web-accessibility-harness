import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from remediation_call_evidence import RecordedModelCalls
from remediation_agent_runtime import AgentRuntime


class RecordedCallsTests(unittest.TestCase):
    def test_paid_invalid_answer_is_saved_before_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(1, 42, .15, 240)
            runtime.skills_for('generate')
            caller = Mock(return_value=('not JSON', 12, 3, .001, .5, 'explicit/model'))
            recorded = RecordedModelCalls(directory, runtime, caller)
            result = recorded({'openrouter_api_key': 'secret'}, 'explicit/model',
                              'Exact prompt', messages=[{'role': 'user', 'content': 'Exact prompt'}])
            with self.assertRaises(ValueError):
                json.loads(result[0])
            text = (Path(directory) / 'model-call-evidence.json').read_text()
            data = json.loads(text)
            self.assertNotIn('secret', text)
            self.assertEqual(data['calls'][0]['prompt'], 'Exact prompt')
            self.assertEqual(data['calls'][0]['cost_usd'], .001)
            self.assertEqual(data['calls'][0]['response'], 'not JSON')
            self.assertEqual(len(data['calls'][0]['response_sha256']), 64)
            self.assertTrue(data['agentic_runtime']['activated_skills'])
            caller.assert_called_once()

    def test_transport_failure_has_no_fabricated_charge(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(1, 42, .15, 240)
            caller = Mock(side_effect=RuntimeError('provider error'))
            recorded = RecordedModelCalls(directory, runtime, caller)
            with self.assertRaisesRegex(RuntimeError, 'provider error'):
                recorded({}, 'explicit/model', 'Task')
            data = json.loads((Path(directory) / 'model-call-evidence.json').read_text())
            self.assertEqual(data['calls'][0]['status'], 'transport_failed')
            self.assertNotIn('cost_usd', data['calls'][0])

    def test_checkpoint_retains_calls_and_real_tool_records(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(1, 42, .15, 240)
            caller = Mock(return_value=('', 2, 0, .01, .2, 'explicit/model'))
            recorded = RecordedModelCalls(directory, runtime, caller)
            recorded({}, 'explicit/model', 'First')
            recorded({}, 'explicit/model', 'Second')
            runtime.tools.records.append({'tool': 'apply_constrained_patch', 'status': 'completed'})
            recorded.checkpoint()
            data = json.loads((Path(directory) / 'model-call-evidence.json').read_text())
            self.assertEqual([c['call_number'] for c in data['calls']], [1, 2])
            self.assertEqual(data['agentic_runtime']['tool_invocations'][0]['tool'], 'apply_constrained_patch')

    def test_resume_preserves_prior_calls_and_does_not_duplicate_paid_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(1, 42, .15, 240)
            caller = Mock(return_value=('saved response', 2, 1, .01, .2, 'explicit/model'))
            original = RecordedModelCalls(directory, runtime, caller)
            original({}, 'explicit/model', 'First')
            original({}, 'explicit/model', 'Pending')
            resumed = RecordedModelCalls(directory, runtime, caller, resume_existing=True)
            resumed({}, 'explicit/model', 'Pending')
            data = json.loads((Path(directory) / 'model-call-evidence.json').read_text())
            self.assertEqual(len(data['calls']), 2)
            self.assertEqual([row['prompt'] for row in data['calls']], ['First','Pending'])
            resumed({}, 'explicit/model', 'Next')
            self.assertEqual(len(resumed.records), 3)

    def test_identical_prompts_in_distinct_calls_can_have_different_valid_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=AgentRuntime(1,42,.15,240)
            identities={False:None,True:'first-call'}
            identity=lambda completed:identities[completed]
            caller=Mock(return_value=('first answer',2,1,.01,.2,'explicit/model'))
            original=RecordedModelCalls(directory,runtime,caller,call_identity=identity)
            original({},'explicit/model','Same evidence')
            identities.update({False:None,True:'second-call'})
            caller.return_value=('another valid answer',2,1,.01,.2,'explicit/model')
            resumed=RecordedModelCalls(directory,runtime,caller,resume_existing=True,call_identity=identity)
            resumed({},'explicit/model','Same evidence')
            self.assertEqual(len(resumed.records),2)
            self.assertEqual([row['provider_call_id'] for row in resumed.records],['first-call','second-call'])

    def test_resume_rejects_a_changed_replayed_response(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(1, 42, .15, 240)
            caller = Mock(return_value=('saved', 2, 1, .01, .2, 'explicit/model'))
            RecordedModelCalls(directory, runtime, caller)({}, 'explicit/model', 'Pending')
            caller.return_value = ('different', 2, 1, .01, .2, 'explicit/model')
            with self.assertRaises(ValueError):
                RecordedModelCalls(directory, runtime, caller, resume_existing=True)({}, 'explicit/model', 'Pending')
            data = json.loads((Path(directory) / 'model-call-evidence.json').read_text())
            self.assertEqual(data['calls'][0]['response'], 'saved')

    def test_resume_replays_exact_paid_bytes_after_json_key_reordering(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(1, 42, .15, 240)
            caller = Mock(return_value=('saved', 2, 1, .01, .2, 'explicit/model'))
            prefix = 'Fixed instructions\nCurrent evidence:\n'
            old = prefix + '{"iteration":4,"feedback":"same"}' + '\nFixed suffix'
            new = prefix + '{"feedback":"same","iteration":4}' + '\nFixed suffix'
            old_messages = [{'role':'user','content':[{'type':'text','text':old},
                                                      {'type':'image_url','image_url':{'url':'data:unchanged'}}]}]
            new_messages = [{'role':'user','content':[{'type':'text','text':new},
                                                      {'type':'image_url','image_url':{'url':'data:unchanged'}}]}]
            RecordedModelCalls(directory, runtime, caller)({},'explicit/model',old,messages=old_messages)
            resumed = RecordedModelCalls(directory, runtime, caller, resume_existing=True)
            resumed({},'explicit/model',new,messages=new_messages)
            self.assertEqual(caller.call_args.args[2], old)
            self.assertEqual(caller.call_args.args[7], old_messages)
            self.assertEqual(resumed.last_prompt, old)
            self.assertEqual(len(resumed.records), 1)

    def test_semantic_patch_or_image_change_cannot_reuse_saved_inputs(self):
        from remediation_call_evidence import equivalent_patch_prompt, equivalent_patch_messages
        first = 'Fixed\nCurrent evidence:\n{"iteration":4,"source":"original"}\nSuffix'
        self.assertFalse(equivalent_patch_prompt(first, first.replace('original','different')))
        self.assertFalse(equivalent_patch_prompt(first, first.replace('Suffix','changed suffix')))
        self.assertFalse(equivalent_patch_messages({'image_url':'first'}, {'image_url':'different'}))

    def test_nested_feedback_json_reuses_exact_paid_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = AgentRuntime(1, 42, .15, 240)
            caller = Mock(return_value=('saved', 2, 1, .01, .2, 'explicit/model'))
            prefix = 'Fixed instructions\nCurrent evidence:\n'
            old = prefix + json.dumps({'iteration': 4, 'feedback': 'Measured: {"axe":0,"lh":96}'})
            new = prefix + json.dumps({'feedback': 'Measured: {"lh":96,"axe":0}', 'iteration': 4})
            RecordedModelCalls(directory, runtime, caller)({}, 'explicit/model', old, messages=[{'role':'user','content':old}])
            resumed = RecordedModelCalls(directory, runtime, caller, resume_existing=True)
            resumed({}, 'explicit/model', new, messages=[{'role':'user','content':new}])
            self.assertEqual(caller.call_args.args[2], old)
            self.assertEqual(len(resumed.records), 1)

    def test_diagnosis_order_only_and_changed_values(self):
        from remediation_call_evidence import equivalent_patch_prompt
        prefix = 'You are the accessibility diagnosis agent BEFORE localized patch generation.\nEvidence: '
        old = prefix + '{"axe":0,"feedback":"same"}'
        reordered = prefix + '{"feedback":"same","axe":0}'
        self.assertTrue(equivalent_patch_prompt(old, reordered))
        self.assertFalse(equivalent_patch_prompt(old, reordered.replace('"axe":0', '"axe":1')))
        self.assertFalse(equivalent_patch_prompt(old, reordered.replace('same', 'different')))
        self.assertFalse(equivalent_patch_prompt(old, reordered + ' More instructions'))

    def test_nested_evidence_keeps_array_order_and_text(self):
        from remediation_call_evidence import equivalent_patch_prompt
        old = 'Fixed\nCurrent evidence:\n' + json.dumps({'feedback':'Items: {"items":[1,2],"text":"Keep  two spaces"}'})
        self.assertFalse(equivalent_patch_prompt(old, old.replace('[1,2]', '[2,1]')))
        self.assertFalse(equivalent_patch_prompt(old, old.replace('Keep  two', 'Keep two')))
