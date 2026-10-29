import copy,json,unittest
from unittest.mock import Mock,patch
from model_catalog_metadata import compatible,discover,normalize,reviewed_metadata,pricing_rates
from remediation_model_choices import default_catalog,validate_catalog
from harness.decision_models import DEFINITIONS,validate_catalogue,snapshot
from harness.contracts import ContractError,model_snapshot

class ModelCatalogueTest(unittest.TestCase):
    def test_admission_filters_actual_json_tasks_not_tools_or_vision(self):
        cloud=reviewed_metadata()['openai/gpt-6-luna']
        text_only=dict(cloud,vision=False,input_modalities=['text'],supported_parameters=['response_format','max_tokens'])
        self.assertTrue(compatible(text_only))
        for value in [dict(text_only,supported_parameters=['tools','max_tokens']),
                      dict(text_only,output_modalities=['image']),dict(text_only,context_length=None),
                      dict(text_only,input_usd_per_million=float('nan')),
                      dict(text_only,supported_parameters=['response_format']),
                      dict(text_only,supported_parameters=['response_format','max_completion_tokens'])]:
            self.assertFalse(compatible(value))
        metadata={cloud['model']:text_only}
        values=[dict(default_catalog()[0],vision=True,supported_parameters=['tools'],input_usd_per_million=0)]
        saved=validate_catalog(values,metadata)
        self.assertFalse(saved[0]['vision']);self.assertEqual(saved[0]['input_usd_per_million'],.1)
        with self.assertRaises(ValueError):validate_catalog(values,{cloud['model']:dict(text_only,supported_parameters=['tools'])})

    def test_dynamic_decisions_tampering_removal_order_and_frozen_identity(self):
        metadata=reviewed_metadata(kind='decisions')
        discovered=metadata['liquid/d1']
        choice=dict(discovered,id=discovered['model'],label='My selector',enabled=True,is_default=True,
                    input_usd_per_million=0,response_model='liquid/different',context_length=999999)
        values=validate_catalogue([choice],metadata)
        self.assertEqual(len(values),1);self.assertEqual(values[0]['label'],'My selector')
        self.assertEqual(values[0]['response_model'],discovered['response_model'])
        self.assertEqual(values[0]['context_length'],discovered['context_length'])
        self.assertEqual(values[0]['input_usd_per_million'],.04)
        frozen=snapshot(values[0]);changed=copy.deepcopy(metadata);changed[discovered['model']]['context_length']=2048
        validate_catalogue([dict(DEFINITIONS[0])],changed) # Remove the other model from future choices.
        self.assertEqual(snapshot(frozen),frozen)
        with self.assertRaises(ContractError):model_snapshot(frozen)
        with self.assertRaises(ContractError):validate_catalogue([dict(choice,is_default=False)],metadata)

    def test_discovery_separates_modalities_and_skips_missing_bounds(self):
        item={'id':'fixture/new','name':'New','canonical_slug':'fixture/new-20261008','context_length':8192,
              'architecture':{'input_modalities':['text'],'output_modalities':['decisions']},
              'pricing':{'prompt':'0.0000001','completion':'0'},'supported_parameters':[]}
        response=Mock();response.json.return_value={'data':[item,dict(item,id='fixture/missing',context_length=0),dict(item,id='~fixture/router')]}
        with patch('model_catalog_metadata.requests.get',return_value=response) as get:
            models=discover({'openrouter_base_url':'https://fixture/api/v1'},'decisions')
        self.assertEqual([m['model'] for m in models],['fixture/new'])
        self.assertEqual(get.call_args.args[0],'https://fixture/api/v1/models?output_modalities=decisions')
        self.assertNotIn('headers',get.call_args.kwargs)

    def test_decision_picker_excludes_text_only_models(self):
        from harness.decision_models import discover_models
        models = [dict(model='fixture/text', vision=False),
                  dict(model='fixture/vision', vision=True)]
        with patch('harness.decision_models.discover', return_value=models):
            self.assertEqual(discover_models({}), [models[1]])

    def test_long_context_pricing_preserves_base_and_bounds_reservations(self):
        model=reviewed_metadata()['anthropic/claude-haiku-5.5']
        self.assertEqual(pricing_rates(model,99999),(.1,.5))
        self.assertEqual(pricing_rates(model,100000),(.5,2.5))
        self.assertEqual(pricing_rates(model),(.5,2.5))
        frozen=model_snapshot(dict(model,id=model['model']))
        self.assertEqual(frozen['input_usd_per_million'],.1)
        self.assertEqual(frozen['pricing_overrides'][0]['min_prompt_tokens'],100000)
