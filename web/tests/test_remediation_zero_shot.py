import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from remediation_zero_shot import execute, persist_observation
from remediation_zero_shot import sole_generation
from harness.contracts import MeasurementIncomplete


class ZeroShotPersistenceTests(unittest.TestCase):
    def test_only_receipt_linked_empty_retry_can_replace_a_generator_transmission(self):
        from harness.store import Store
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            failed = {'id':'failed','logical_key':'attempt:call:0','status':'transport_error',
                      'response_id':None,'cost_status':'reconciled','cost':0,'request_hash':'same'}
            good = {'id':'good','logical_key':'attempt:call:0:reconciled-transport-retry:1',
                    'status':'received','response_id':'response','cost_status':'provider_reported',
                    'cost':.01,'request_hash':'same'}
            calls = [failed, good]
            bridge = SimpleNamespace(store=store,cid='campaign',rid='run',
                providers=SimpleNamespace(ledger=SimpleNamespace(rows=lambda *args:calls)))
            with self.assertRaises(MeasurementIncomplete):
                sole_generation(bridge)
            store.append('call_retry_authorization', {'call_id':'failed','retry_key':good['logical_key']}, 'campaign')
            self.assertEqual(sole_generation(bridge), (good, ['failed']))
            good['request_hash'] = 'changed'
            with self.assertRaises(MeasurementIncomplete):
                sole_generation(bridge)
            good['request_hash'] = 'same'
            failed['cost_status'] = 'unknown'
            with self.assertRaises(MeasurementIncomplete):
                sole_generation(bridge)
            failed['cost_status'] = 'reconciled'
            calls.append(dict(good,id='second',logical_key='attempt:call:1'))
            with self.assertRaises(MeasurementIncomplete):
                sole_generation(bridge)

    def test_reclassified_response_clears_stale_page_metrics_without_a_second_generation(self):
        raw = 'Cannot return the page; its `<html>` is too large.'
        call = {'id': 'generator', 'logical_key': 'attempt:call:0', 'response_id': 'receipt',
                'input_tokens': 30, 'output_tokens': 8, 'cost': .01, 'elapsed': 1, 'model': 'fixture/model'}
        store = Mock()
        store.list.return_value = []
        store.read_blob.return_value = json.dumps({'choices': [{'finish_reason': 'stop'}]}).encode()
        bridge = SimpleNamespace(store=store, cid='campaign', rid='run',
            worker={'reasoning_effort': 'low'},
            providers=SimpleNamespace(ledger=SimpleNamespace(rows=lambda *args: [call])))
        outcome = {'axe': None, 'lighthouse': None, 'seconds': 2,
                   'costs': {'cost_usd': .01, 'input_tokens': 30, 'output_tokens': 8, 'call_ids': ['generator']}}
        cursor = Mock(); cursor.fetchone.return_value = {'id': 2}; connection = Mock()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'response.txt'
            path.write_text(raw)
            persist_observation(bridge, {}, {'id': 1, 'model_config_json': '{}'}, Path(directory),
                cursor, connection, lambda settings: 'now',
                (raw, {'evaluable': False}, (raw, 30, 8, .01, 1, 'fixture/model'), path, 'url', {}, outcome))
        self.assertFalse(any(c.args[0].startswith('INSERT') for c in cursor.execute.call_args_list))
        clear = next(c for c in cursor.execute.call_args_list if 'axe_violations=NULL' in c.args[0])
        self.assertIn('lighthouse_score=NULL', clear.args[0])
        self.assertIn('screenshot_path=NULL', clear.args[0])
        self.assertIn('dom_changes_json=NULL', clear.args[0])
        strategy_call = next(c for c in cursor.execute.call_args_list if 'SET strategy_json=' in c.args[0])
        self.assertFalse(json.loads(strategy_call.args[1][0])['measured_candidate'])
        connection.commit.assert_called_once()

    def test_completed_measurement_recovers_without_generation_and_key_fits_schema(self):
        candidate = '<main>partial'
        outcome = {'selected': {'source_id': 'html', 'audit_id': None, 'original': False},
                   'axe': None, 'lighthouse': None, 'seconds': 2,
                   'costs': {'cost_usd': .01, 'input_tokens': 3, 'output_tokens': 4, 'call_ids': ['call']}}
        evidence = {'evaluable': False, 'output': 'No paint'}
        call = {'logical_key': 'attempt:call:0', 'id': 'call', 'input_tokens': 3,
                'output_tokens': 4, 'cost': .01, 'elapsed': 1, 'model': 'fixture/model', 'response_id': 'response'}
        store = Mock()
        store.list.return_value = []
        store.get.return_value = {'data': outcome}
        store.read_blob.side_effect = lambda key: (candidate.encode() if key == 'html' else
            json.dumps({'choices': [{'finish_reason': 'length'}]}).encode())
        bridge = SimpleNamespace(store=store, rid='sql-run-1', cid='campaign',
            state={'status': 'completed'}, condition={'worker_id': 'worker'},
            manifest={'workers': [{'id': 'worker', 'model': 'fixture/model'}]},
            providers=SimpleNamespace(ledger=SimpleNamespace(rows=lambda *args: [call])))
        cursor = Mock(); cursor.fetchone.return_value = None; cursor.lastrowid = 2
        connection = Mock(); model_call = Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'baseline-output.json').write_text(json.dumps(evidence))
            (root/'one-shot-original-response.txt').write_text(candidate)
            (root/'generation-input.html').write_text('<html>source</html>')
            result = execute(bridge, {}, {'id': 1, 'model_config_json': '{}'}, '<html>source</html>',
                             root, cursor, connection, model_call, lambda settings: 'now')
        model_call.assert_not_called()
        self.assertEqual(result['axe'], None)
        insert = next(c for c in cursor.execute.call_args_list if c.args[0].startswith('INSERT'))
        names = insert.args[0].split('(', 1)[1].split(')', 1)[0].split(',')
        values = dict(zip(names, insert.args[1]))
        self.assertLessEqual(len(values['candidate_key']), 36)
        self.assertEqual(values['output_path'].split('/')[-1], 'response.txt')
        self.assertIsNone(values['axe_violations'])
        self.assertIsNone(values['lighthouse_score'])
        connection.commit.assert_called_once()


    def test_failed_taxonomy_recovery_remeasures_the_existing_single_candidate(self):
        selected = {'source_id': 'html', 'audit_id': 'audit', 'original': False}
        saved = {'selected': selected, 'attempts': ['attempt-0'],
                 'taxonomy_measurement': {'status': 'partial'}}
        finished = dict(saved, taxonomy_measurement={'status': 'completed'})
        store = Mock()
        store.list.return_value = []
        store.get.side_effect = lambda key: {'data': saved if key == 'run-result'
                                            else {'raw_result': {'axe': {}}}}
        store.read_blob.return_value = b'<main>saved candidate</main>'
        call = {'id': 'paid', 'logical_key': 'attempt:call:0', 'response_id': 'response',
                'input_tokens': 10, 'output_tokens': 20, 'cost': .1, 'elapsed': 2,
                'model': 'fixture/model'}
        bridge = SimpleNamespace(store=store, rid='run', cid='campaign',
            execution_revision={'id': 'revision'},
            state={'status': 'failed', 'iteration': 1, 'attempts': ['attempt-0'],
                   'incumbent': selected},
            condition={'worker_id': 'worker'},
            manifest={'workers': [{'id': 'worker', 'model': 'fixture/model'}]},
            providers=SimpleNamespace(ledger=SimpleNamespace(rows=lambda *args: [call])),
            finish=Mock(return_value=finished))
        model_call = Mock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'baseline-output.json').write_text(json.dumps({'evaluable': True}))
            (root/'one-shot-original-response.txt').write_text('<main>saved candidate</main>')
            with patch('remediation_zero_shot.persist_observation', return_value=finished) as persist:
                result = execute(bridge, {}, {'id': 1}, 'source', root,
                                 Mock(), Mock(), model_call, lambda _: 'now')
        bridge.finish.assert_called_once()
        model_call.assert_not_called()
        self.assertEqual(result['taxonomy_measurement']['status'], 'completed')
        self.assertEqual(bridge.state['attempts'], ['attempt-0'])
        self.assertEqual(persist.call_args.args[-1][-1], finished)
