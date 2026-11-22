import json
import tempfile
import unittest
from unittest.mock import patch

from harness.contracts import ContractError
from harness.store import Store
from harness.zero_shot_delivery import first_page, delivery_request, validate_timing_revision


class DeliverySelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(self.directory.name)
        self.request = {'model': 'test/model', 'messages': [{'role': 'user', 'content': 'Repair <main>source</main>'}]}

    def call(self, number, content, request=None):
        request = self.store.append('call_request', {'request': request or self.request})
        response = self.store.blob(json.dumps({'choices': [{'message': {'content': content}}]}), 'provider_response')
        return dict(id=str(number), created=number, account='repair', status='received',
                    cost_status='provider_reported', request_id=request['id'], response_id=response['id'])

    def test_refusal_stays_missing_and_first_fragment_is_measured(self):
        first = self.call(1, 'Cannot return a complete page; `<html>` is only an example.')
        self.assertIsNone(first_page(self.store, [first], self.request))
        second = self.call(2, '<main>Imperfect but actual generated content</main>')
        selected = first_page(self.store, [first, second], self.request)
        self.assertEqual(selected[0]['id'], '2')
        self.assertEqual(selected[1], '<main>Imperfect but actual generated content</main>')

    def test_a_second_generation_after_html_cannot_replace_the_first(self):
        calls = [self.call(1, '<main>Bad output</main>'), self.call(2, '<html>Better output</html>')]
        with self.assertRaises(ContractError):
            first_page(self.store, calls, self.request)

    def test_audit_feedback_or_changed_source_cannot_enter_a_retry(self):
        changed = {'model': 'test/model', 'messages': [{'role': 'user', 'content': 'Repair source using these audit findings'}]}
        with self.assertRaises(ContractError):
            first_page(self.store, [self.call(1, '<main>Page</main>', changed)], self.request)

    def test_unresolved_charge_blocks_delivery_selection(self):
        call = self.call(1, '<main>Page</main>')
        call['cost_status'] = 'unknown'
        with self.assertRaises(ContractError):
            first_page(self.store, [call], self.request)

    def test_declared_delivery_clarification_preserves_source_and_parameters(self):
        prefix = 'Return HTML directly, retaining user-facing content.\n\n'
        clarified = delivery_request(self.request, prefix)
        self.assertEqual(clarified['messages'][0]['content'], prefix+self.request['messages'][0]['content'])
        self.assertEqual(self.request['messages'][0]['content'], 'Repair <main>source</main>')
        call = self.call(1, '<main>Page</main>', clarified)
        self.assertIsNotNone(first_page(self.store, [call], self.request, [prefix]))
        with self.assertRaises(ContractError):
            first_page(self.store, [call], self.request)

    def test_timing_excludes_only_operator_waits_and_keeps_resources(self):
        source=self.store.blob('<main>Page</main>','candidate_html')
        audit=self.store.append('audit',{})
        original=self.store.append('run_result',{'seconds':6})
        incumbent={'run_id':'run','seconds':100,'selected':{'source_id':source['id'],'audit_id':audit['id']},
                   'costs':{'cost_usd':.04,'call_ids':['first','second']}}
        parent=self.store.append('zero_shot_delivery_revision',{'parent_outcome_id':original['id'],
            'measurement_campaign_id':'phase','outcome':incumbent})
        with self.store.connect() as db:
            db.execute('UPDATE records SET created=45 WHERE id=?',(audit['id'],))
            db.execute('UPDATE records SET created=50 WHERE id=?',(parent['id'],))
        outcome=dict(incumbent,seconds=21,resource_time_basis='Active requests and evaluation')
        data={'parent_outcome_id':parent['id'],'outcome':outcome,'measurement_start':40,'measurement_end':50,
              'candidate_sha256':source['data']['sha256'],'raw_receipts_modified':False}
        calls=[{'account':'repair','created':10,'elapsed':2},{'account':'repair','created':30,'elapsed':3}]
        with patch('harness.zero_shot_delivery.Ledger.rows',return_value=calls):
            validate_timing_revision(self.store,{'data':data},incumbent,[])
            for fields in ({'seconds':20},{'costs':{'cost_usd':0,'call_ids':[]}}):
                changed=dict(data,outcome={**outcome,**fields})
                with self.assertRaises(ContractError):
                    validate_timing_revision(self.store,{'data':changed},incumbent,[])


if __name__ == '__main__':
    unittest.main()
