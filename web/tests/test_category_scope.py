import json
import unittest
from unittest.mock import MagicMock, patch
import classify_site_categories as categories
from category_models import freeze_category_model


class CategoryScopeTests(unittest.TestCase):
    def test_saved_non_openai_default_dispatches_cloud_with_frozen_settings(self):
        snapshot=freeze_category_model({'id':'anthropic/example@high',
            'model':'anthropic/example','provider':'cloud','config':{
                'base_url':'https://saved.invalid/v1','model':'anthropic/example',
                'reasoning_effort':'high','supported_parameters':['reasoning']}})
        connection=MagicMock(); connection.cursor.return_value.fetchall.return_value=[{'id':7,'url':'https://example.org/'}]
        accounting=MagicMock(); response=MagicMock()
        response.json.return_value={'usage':{'cost':0.001},'choices':[{'message':{'content':'{"7":"Education"}'}}]}
        with (patch.object(categories,'get_connection',side_effect=[connection,accounting]),
              patch.object(categories,'get_settings',return_value={'openrouter_api_key':'current-secret','openrouter_base_url':'https://changed.invalid'}),
              patch.object(categories,'local_chat') as local,
              patch.object(categories.requests,'post',return_value=response) as cloud):
            result=categories.classify_managed_urls(one_batch=True,model='anthropic/example',model_config=json.dumps(snapshot))
        self.assertEqual(result,(1,'anthropic/example'))
        self.assertEqual(cloud.call_args.args[0],'https://saved.invalid/v1/chat/completions')
        self.assertEqual(cloud.call_args.kwargs['json']['reasoning'],{'effort':'high'})
        self.assertNotIn('response_format',cloud.call_args.kwargs['json'])
        local.assert_not_called(); accounting.commit.assert_called_once()

    def test_selected_local_model_is_not_replaced_by_configuration(self):
        snapshot=freeze_category_model({'id':'ollama/llama:latest','model':'ollama/llama:latest',
            'provider':'local','config':{'model':'llama:latest','base_url':'http://saved:11434/v1'}})
        connection=MagicMock(); connection.cursor.return_value.fetchall.return_value=[{'id':7,'url':'https://example.org/'}]
        with (patch.object(categories,'get_connection',return_value=connection),
              patch.object(categories,'get_settings',return_value={'ollama_model':'gemma4:latest'}),
              patch.object(categories,'local_chat',return_value=('{"7":"Education"}',20,10)) as local,
              patch.object(categories.requests,'post') as cloud):
            categories.classify_managed_urls(one_batch=True,model='ollama/llama:latest',model_config=snapshot)
        self.assertEqual(local.call_args.args[0]['model'],'llama:latest')
        self.assertEqual(local.call_args.args[0]['base_url'],'http://saved:11434/v1')
        cloud.assert_not_called()

    def test_gemma4_category_selection_dispatches_locally_without_cloud(self):
        connection=MagicMock(); cursor=connection.cursor.return_value
        cursor.fetchall.return_value=[{'id':7,'url':'https://example.org/','page_title':'University'}]
        config={'model':'gemma4:latest','base_url':'http://host.docker.internal:11434/v1',
                'reasoning_effort':'none','vision':True}
        with (patch.object(categories,'get_connection',return_value=connection),
              patch.object(categories,'get_settings',return_value={}),
              patch.object(categories,'local_configuration',return_value=config),
              patch.object(categories,'local_chat',return_value=('{"7":"Education"}',20,10)) as local,
              patch.object(categories.requests,'post') as cloud):
            result=categories.classify_managed_urls(one_batch=True,model='ollama/gemma4:latest')
        self.assertEqual(result,(1,'ollama/gemma4:latest'))
        self.assertEqual(local.call_args.args[0]['model'],'gemma4:latest')
        self.assertTrue(local.call_args.kwargs['json_mode'])
        cloud.assert_not_called()

    def run_batch(self, content, rows=None):
        connection=MagicMock(); cursor=connection.cursor.return_value
        cursor.fetchall.return_value=rows or [{'id':7,'url':'https://example.org/','page_title':'University','normalized_url':'https://example.org/'}]
        accounting=MagicMock(); response=MagicMock()
        response.json.return_value={'usage':{'prompt_tokens':20,'completion_tokens':10,'cost':0.001},
                                    'choices':[{'message':{'content':content}}]}
        patches=(patch.object(categories,'get_connection',side_effect=[connection,accounting]),
                 patch.object(categories,'get_settings',return_value={'openrouter_base_url':'https://example.invalid','openrouter_api_key':'not-a-key'}),
                 patch.object(categories,'local_configuration',return_value=None),
                 patch.object(categories.requests,'post',return_value=response))
        with patches[0],patches[1],patches[2],patches[3] as request:
            result=categories.classify_managed_urls(one_batch=True,model='openai/gpt-6-luna',experiment_id=131)
        return result,cursor,accounting,request

    def test_cloud_scope_and_luna_parameters(self):
        result,cursor,accounting,request=self.run_batch(json.dumps({'7':'Education'}))
        self.assertEqual(result[0],1)
        sql,params=cursor.execute.call_args_list[0].args
        self.assertIn('r.experiment_id=%s',sql); self.assertIn('LIMIT %s',sql)
        self.assertEqual(params,(131,10))
        payload=request.call_args.kwargs['json']
        self.assertEqual(payload['reasoning'],{'effort':'low'})
        self.assertNotIn('temperature',payload)
        accounting.commit.assert_called_once()

    def test_usage_is_committed_before_invalid_paid_response_is_rejected(self):
        connection=MagicMock(); connection.cursor.return_value.fetchall.return_value=[{'id':7,'url':'https://example.org/'}]
        accounting=MagicMock(); response=MagicMock()
        response.json.return_value={'usage':{'cost':0.002},'choices':[{'message':{'content':'not-json'}}]}
        with (patch.object(categories,'get_connection',side_effect=[connection,accounting]),
              patch.object(categories,'get_settings',return_value={'openrouter_base_url':'https://example.invalid','openrouter_api_key':'not-a-key'}),
              patch.object(categories,'local_configuration',return_value=None),
              patch.object(categories.requests,'post',return_value=response)):
            with self.assertRaises(json.JSONDecodeError):
                categories.classify_managed_urls(one_batch=True,model='openai/gpt-6-luna')
        accounting.commit.assert_called_once()
        connection.commit.assert_not_called()

    def test_partial_valid_assignments_preserve_omitted_ids_for_next_batch(self):
        result,cursor,accounting,_=self.run_batch('{"7":"Education"}',rows=[
            {'id':7,'url':'https://university.example/'},
            {'id':8,'url':'https://shop.example/'}])
        self.assertEqual(result[0],1)
        updates=[call.args for call in cursor.execute.call_args_list if 'UPDATE experiment_results' in call.args[0]]
        self.assertEqual(len(updates),1)
        self.assertEqual(updates[0][1][-1],7)
        accounting.commit.assert_called_once()

    def test_unknown_id_or_category_or_empty_response_is_rejected(self):
        for content in ('{"8":"Education"}','{"7":"Invented"}','{}','{"7":null}'):
            with self.subTest(content=content), self.assertRaises(RuntimeError):
                self.run_batch(content)

    def test_invalid_batch_retries_single_record_without_switching_model(self):
        connection=MagicMock()
        connection.cursor.return_value.fetchone.return_value={
            'status':'queued','model':'openai/gpt-6-luna','experiment_id':131,
            'total_urls':2,'completed_urls':0}
        with (patch.object(categories,'get_connection',return_value=connection),
              patch.object(categories,'classify_managed_urls',side_effect=[
                  categories.CategoryResponseError('omitted label'),
                  (1,'openai/gpt-6-luna'),(0,'openai/gpt-6-luna')]) as classify):
            categories.process_managed_url_categorization()
        self.assertEqual([c.kwargs['batch_size'] for c in classify.call_args_list],[10,1,10])
        self.assertTrue(all(c.kwargs['model']=='openai/gpt-6-luna' and c.kwargs['experiment_id']==131 for c in classify.call_args_list))

    def test_invalid_response_retries_are_bounded(self):
        connection=MagicMock()
        connection.cursor.return_value.fetchone.return_value={
            'status':'queued','model':'openai/gpt-6-luna','experiment_id':131,
            'total_urls':2,'completed_urls':0}
        with (patch.object(categories,'get_connection',return_value=connection),
              patch.object(categories,'classify_managed_urls',side_effect=categories.CategoryResponseError('empty')) as classify):
            with self.assertRaises(categories.CategoryResponseError):
                categories.process_managed_url_categorization()
        self.assertEqual(classify.call_count,3)


if __name__=='__main__': unittest.main()
