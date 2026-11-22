import tempfile
import unittest
from types import SimpleNamespace
from harness.store import Store
from accessibility_taxonomy.checkpoints import assessment_checkpoint, save_assessment


class CheckpointTests(unittest.TestCase):
    def test_http_error_completion_requires_matching_retry_and_runtime_receipts(self):
        for error in ('Provider returned HTTP 503',
                      'Provider error 503; response and billing evidence retained'):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as root:
                store = Store(root)
                store.append('campaign', {'campaign_cost_limit': 5}, ident='campaign')
                original = store.append('taxonomy_assessment', {
                    'errors': [error], 'call_ids': ['failed-call'],
                    'document_sha256': 'unchanged-document'}, 'campaign', 'assessment')
                provider = SimpleNamespace(campaign='campaign', manifest={
                    'campaign_cost_limit': 5, 'runtime_snapshot': {'code_digest': 'fixed'}})
                store.append('campaign_execution_revision', {
                    'runtime_snapshot': {'code_digest': 'fixed'}, 'raw_receipts_modified': False},
                    'campaign', 'revision')
                self.assertEqual(assessment_checkpoint(store, provider, 'assessment')[0], original)
                store.append('call_retry_authorization', {'call_id': 'another-call'}, 'campaign')
                self.assertEqual(assessment_checkpoint(store, provider, 'assessment')[0], original)
                store.append('call_retry_authorization', {'call_id': 'failed-call'}, 'campaign')
                provider.manifest['runtime_snapshot'] = {'code_digest': 'different'}
                self.assertEqual(assessment_checkpoint(store, provider, 'assessment')[0], original)
                provider.manifest['runtime_snapshot'] = {'code_digest': 'fixed'}
                saved, ident, parent = assessment_checkpoint(store, provider, 'assessment')
                self.assertIsNone(saved)
                self.assertEqual(parent, original['id'])
                completed = save_assessment(store, provider, ident, parent, {
                    'errors': [], 'document_sha256': 'unchanged-document'})
                self.assertEqual(store.get(original['id']), original)
                self.assertEqual(assessment_checkpoint(store, provider, 'assessment')[0], completed)
                permanent = store.append('taxonomy_assessment', {
                    'errors': [error, 'Invalid contextual decision'], 'call_ids': ['failed-call']},
                    'campaign', 'invalid-assessment')
                self.assertEqual(assessment_checkpoint(store, provider, permanent['id'])[0], permanent)

    def test_completed_evidence_is_shared_without_replacing_its_failed_parent(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            parent = store.append('taxonomy_assessment', {'errors':['Provider error 502']},
                                  'first', 'shared-assessment')
            completed = store.append('taxonomy_assessment', {
                'errors':[], 'completion_parent_assessment_id':parent['id']},
                'first', parent['id'] + '-completed')
            provider = SimpleNamespace(campaign='second', manifest={})
            saved, _, reference = assessment_checkpoint(store, provider, parent['id'])
            self.assertEqual(saved, completed)
            self.assertEqual(reference, parent['id'])
            self.assertEqual(store.get(parent['id']), parent)

    def test_visual_configuration_recovery_requires_a_recorded_runtime_amendment(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            store.append('campaign', {'campaign_cost_limit': 5}, ident='campaign')
            original = store.append('taxonomy_assessment', {
                'errors': ['Luna light vision configuration must be explicitly available'],
                'document_sha256': 'same'}, 'campaign', 'assessment')
            providers = SimpleNamespace(campaign='campaign', manifest={
                'campaign_cost_limit': 5, 'runtime_snapshot': {'code_digest': 'fixed'}})
            self.assertEqual(assessment_checkpoint(store, providers, 'assessment')[0], original)
            store.append('campaign_execution_revision', {
                'runtime_snapshot': {'code_digest': 'fixed'}, 'raw_receipts_modified': False},
                'campaign', 'revision')
            cached, ident, parent = assessment_checkpoint(store, providers, 'assessment')
            self.assertIsNone(cached)
            self.assertEqual(ident, 'assessment-completion-revision')
            completed = save_assessment(store, providers, ident, parent, {'errors': []})
            self.assertEqual(store.get('assessment'), original)
            self.assertEqual(assessment_checkpoint(store, providers, 'assessment')[0], completed)

    def test_larger_authorized_budget_preserves_partial_and_reuses_completed_receipt(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            store.append('campaign', {'campaign_cost_limit': .25}, ident='old')
            original = store.append('taxonomy_assessment', {'errors':['Campaign cost limit reached'],
                'document_sha256':'same'}, 'old', 'assessment')
            same = SimpleNamespace(campaign='same',manifest={'campaign_cost_limit':.25})
            self.assertEqual(assessment_checkpoint(store,same,'assessment')[0], original)
            increased = SimpleNamespace(campaign='new',manifest={'campaign_cost_limit':5})
            cached, ident, parent = assessment_checkpoint(store,increased,'assessment')
            self.assertIsNone(cached)
            completed = save_assessment(store,increased,ident,parent,{'errors':[], 'document_sha256':'same'})
            self.assertEqual(store.get('assessment'),original)
            self.assertEqual(completed['data']['completion_parent_assessment_id'],'assessment')
            self.assertEqual(assessment_checkpoint(store,same,'assessment')[0],completed)

    def test_parse_failure_is_never_retried_and_partial_attempt_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root)
            store.append('campaign',{'campaign_cost_limit':.25},ident='old')
            p=SimpleNamespace(campaign='new',manifest={'campaign_cost_limit':5})
            invalid=store.append('taxonomy_assessment',{'errors':['Invalid contextual decision']},'old','invalid')
            self.assertEqual(assessment_checkpoint(store,p,'invalid')[0],invalid)
            store.append('taxonomy_assessment',{'errors':['Campaign cost limit reached']},'old','budget')
            _,ident,parent=assessment_checkpoint(store,p,'budget')
            attempt=save_assessment(store,p,ident,parent,{'errors':['Campaign cost limit reached']})
            self.assertEqual(assessment_checkpoint(store,p,'budget')[0],attempt)

    def test_census_completion_reuses_paid_batch_and_only_requests_missing_batch(self):
        import json
        from unittest.mock import patch
        from harness.providers import BudgetStop
        from accessibility_taxonomy.assessment import _assess_base
        with tempfile.TemporaryDirectory() as root:
            store=Store(root)
            store.append('campaign',{'campaign_cost_limit':.25},ident='old')
            html=store.blob('<html></html>','html')['id']
            axe=store.blob(json.dumps({'violations':[]}),'axe')['id']
            audit={'id':'audit','data':{'status':'completed','artifacts':{'rendered':html,'axe':axe}}}
            rows=[{'opportunity_id':str(i),'type':'heading-not-descriptive','status':'insufficient_evidence',
                'method':'decisions','context':{}} for i in range(21)]
            record={'opportunities':rows,'document_sha256':'doc','type_coverage':{},'scope':{}}
            p=SimpleNamespace(campaign='old',manifest={'campaign_cost_limit':.25},ledger=SimpleNamespace(rows=lambda:[]))
            paid=[]
            def judge(store,providers,run,ident,model,evidence,batch):
                try:return store.get(ident)
                except KeyError:pass
                if providers.campaign=='old' and len(batch)==1:raise BudgetStop('Campaign cost limit reached')
                paid.append(ident)
                return store.append('taxonomy_judgment',{'opportunities':[dict(r,status='passed') for r in batch]},providers.campaign,ident)
            with patch('accessibility_taxonomy.assessment.inventory',side_effect=lambda *args: __import__('copy').deepcopy(record)),patch('accessibility_taxonomy.assessment.contextual_review',side_effect=judge):
                partial=_assess_base(store,p,'run',audit,'https://example.com',{})
                self.assertEqual(len(paid),1)
                p.campaign='new';p.manifest['campaign_cost_limit']=5
                completed=_assess_base(store,p,'new',audit,'https://example.com',{})
                self.assertEqual(len(paid),2)
                self.assertEqual(completed['data']['errors'],[])
                self.assertTrue(all(r['status']=='passed' for r in completed['data']['opportunities']))
                self.assertEqual(store.get(partial['id']),partial)
                self.assertEqual(_assess_base(store,p,'new',audit,'https://example.com',{}),completed)
                self.assertEqual(len(paid),2)
