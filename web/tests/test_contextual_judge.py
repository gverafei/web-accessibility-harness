import json
import tempfile
import unittest
from unittest.mock import Mock

from accessibility_taxonomy.contextual_judge import VERSION, DECISIONS_PROTOCOL, ask, default_model, default_configuration, from_manifest
from accessibility_taxonomy import contextual_review
from accessibility_taxonomy.consistency import compare
from accessibility_taxonomy.image_evidence import vision_worker
from harness.contracts import ContractError, validate_manifest
from harness.decision_models import DEFINITIONS
from harness.store import Store


class ContextualJudgeTests(unittest.TestCase):
    def setUp(self):
        self.model = default_model({})
        self.questions = [dict(name='title',type='choice',instructions='Exact observed title/body and criterion',
                               choices=[dict(value='passed',description='Matches topic'),
                                        dict(value='failed',description='Contradicts topic')])]

    def test_high_judge_receives_closed_evidence_without_expected_answer_and_uses_review(self):
        provider=Mock()
        provider.chat.return_value='{"title":"passed"}'
        answer=ask(provider,'r','judgment',self.model,'exact state',self.questions)
        self.assertEqual(answer,{'title':{'type':'choice','choice':'passed'}})
        provider.decisions.assert_not_called()
        args=provider.chat.call_args.args
        self.assertEqual(args[:4],('r','review','judgment',self.model))
        logical=json.loads(args[4].split('\n',1)[1])
        self.assertEqual(logical['state'],'exact state')
        self.assertEqual(logical['questions']['title']['instructions'],self.questions[0]['instructions'])
        schema=provider.chat.call_args.kwargs['response_schema']
        self.assertFalse(schema['additionalProperties'])
        self.assertEqual(schema['required'],['title'])

    def test_invalid_or_incomplete_answer_is_not_cached_as_success(self):
        for answer in ('{}','{"title":"maybe"}','{"title":true}','{"title":"passed","other":"passed"}'):
            with self.subTest(answer=answer):
                provider=Mock();provider.chat.return_value=answer
                with self.assertRaises(ContractError):ask(provider,'r','k',self.model,'state',self.questions)
                provider.chat.assert_called_once();provider.decisions.assert_not_called()

    def test_legacy_transport_is_unchanged_and_no_model_substitution(self):
        provider=Mock();legacy={'model':'openai/gpt-6-luna-decisions'}
        ask(provider,'r','k',legacy,'state',self.questions)
        provider.decisions.assert_called_once_with('r','review','k','state',self.questions,model=legacy,image_parts=())
        provider.chat.assert_not_called()
        self.assertIs(from_manifest({'decision_model':legacy},legacy),legacy)
        with self.assertRaises(ContractError):from_manifest({'contextual_judge_model':self.model},legacy)
        with self.assertRaises(ContractError):from_manifest({'contextual_judge_model':self.model|{'reasoning_effort':'low'},'contextual_judge_protocol':VERSION},legacy)

    def test_high_judge_cache_is_separate_from_decisions_and_reuses_identical_evidence(self):
        row=dict(type='page-title-not-descriptive',opportunity_id='title',identity_basis='title::Example',
                 impact='serious',method='decisions',status='insufficient_evidence',
                 context={'element':{'tag':'title','text':'Example','attributes':{}},'observed_text':'Example services'})
        with tempfile.TemporaryDirectory()as root:
            store=Store(root);provider=Mock(campaign='c')
            provider.decisions.return_value={'title':{'type':'choice','choice':'failed'}}
            old=contextual_review(store,provider,'r','old',{}, {'origin':'https://example.org'},[row])
            provider.chat.return_value='{"title":"passed"}'
            new=contextual_review(store,provider,'r','new',self.model,{'origin':'https://example.org'},[row])
            again=contextual_review(store,provider,'r','again',self.model,{'origin':'https://example.org'},[row])
            self.assertEqual(old['data']['opportunities'][0]['status'],'failed')
            self.assertEqual(new['data']['opportunities'][0]['status'],'passed')
            self.assertEqual(new['data']['opportunities'][0]['method'],'luna_contextual')
            self.assertEqual(new['data']['judge_protocol'],VERSION)
            provider.chat.assert_called_once()
            self.assertEqual(new['data']['judgment_cache_ids'],again['data']['judgment_cache_ids'])

    def test_contextual_vision_uses_same_high_judge_without_changing_worker_pool(self):
        manifest=dict(workers=[self.model|{'reasoning_effort':'low'}],
                      contextual_judge_model=self.model,contextual_judge_protocol=VERSION)
        self.assertEqual(vision_worker(manifest)['reasoning_effort'],'high')
        self.assertEqual(manifest['workers'][0]['reasoning_effort'],'low')

    def test_new_roles_keep_decisions_for_context_and_light_for_images_outside_worker_pool(self):
        decision = DEFINITIONS[0]
        roles = default_configuration({}, decision)
        manifest = dict(roles, decision_model=decision, workers=[self.model])
        self.assertEqual(from_manifest(manifest)['model'], 'openai/gpt-6-luna-decisions')
        self.assertEqual(manifest['contextual_judge_protocol'], DECISIONS_PROTOCOL)
        self.assertEqual(vision_worker(manifest)['reasoning_effort'], 'low')
        self.assertEqual(manifest['workers'], [self.model])
        provider = Mock()
        judge = from_manifest(manifest)
        ask(provider, 'r', 'k', judge, 'state', self.questions)
        provider.decisions.assert_called_once()
        provider.chat.assert_not_called()

    def test_role_manifest_round_trip_preserves_models_and_rejects_missing_or_changed_image_role(self):
        roles = default_configuration({}, DEFINITIONS[0])
        manifest = dict(name='Roles fixture',study_id='fixture',seed='1',mode='frozen',partition='test',
            source=dict(kind='urls',urls=['https://fixture.example/']), workers=[self.model],
            capture_verifier=self.model, conditions=[dict(id='P1',level=1,worker_id=self.model['id'],selector='fixed')],
            corpus_id='fixture-corpus',decision_model=DEFINITIONS[0],max_iterations=1,
            repair_budget=dict(max_cost_usd=1,max_seconds=60,max_calls=2,max_output_tokens=1000),
            review_budget=dict(max_cost_usd=1,max_seconds=60,max_calls=2,max_output_tokens=1000),
            campaign_cost_limit=2, **roles)
        frozen = validate_manifest(manifest)
        self.assertEqual(frozen['contextual_judge_protocol'], DECISIONS_PROTOCOL)
        self.assertEqual(from_manifest(frozen), frozen['decision_model'])
        self.assertEqual(vision_worker(frozen), frozen['image_judge_model'])
        without_image = dict(manifest)
        without_image.pop('image_judge_model')
        with self.assertRaises(ContractError): validate_manifest(without_image)
        for changed in ({'reasoning_effort':'high'}, {'vision':False}, {'provider':'ollama'}):
            with self.subTest(changed=changed):
                invalid = dict(manifest,image_judge_model=dict(roles['image_judge_model'],**changed))
                with self.assertRaises(ContractError): validate_manifest(invalid)
        with self.assertRaises(ContractError):
            validate_manifest(dict(manifest,image_judge_protocol='unknown'))

    def test_consistency_guard_remains_active_for_high_contextual_judgments(self):
        row=dict(type='page-title-not-descriptive',opportunity_id='title',identity_basis='title::Example',
                 method='luna_contextual',status='passed',context={'element':{'tag':'title','text':'Example'}})
        result=compare({'model':self.model,'opportunities':[row]},
                       {'model':self.model,'opportunities':[row|{'status':'failed'}]})
        self.assertTrue(result['review_required'])
        self.assertEqual(result['changes'][0]['classification'],'identical_context_verdict_conflict')
