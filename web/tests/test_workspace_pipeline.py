import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from werkzeug.datastructures import MultiDict

from main import create_app
from harness.store import Store
from workspace_pipeline import submission_values, enqueue, advance


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = Store(self.temporary.name)
        self.app = create_app({'TESTING':True,'HARNESS_ROOT':self.temporary.name})
        self.settings = {'app_timezone':'UTC','axe_standard':'wcag22aa','axe_include_best_practices':'false'}
        self.options = {'corpora':[{'id':'corpus'}],'verifiers':[{'id':'verifier'}]}
        self.form = MultiDict(dict(urls='https://example.org/', strategy='P5',selected_model='worker',
            max_cost_usd='0.25',max_iterations='5',max_execution_seconds='900',
            harness_corpus='corpus',harness_verifier='verifier',act_grounding='on'))
        self.choice = patch('workspace_pipeline.model_choice', return_value={'id':'worker'})
        self.choice.start()
        self.addCleanup(self.choice.stop)

    def test_urls_are_normalized_and_duplicates_do_not_multiply_spending(self):
        self.form['urls']='example.org\nhttps://example.org\nhttps://example.net/'
        configuration = submission_values(self.form,self.settings,self.options)
        self.assertEqual(configuration['urls'],['https://example.org','https://example.net/'])

    def test_default_strategy_is_p2_and_console_options_follow_policy_order(self):
        from bs4 import BeautifulSoup
        from flask import render_template
        form = self.form.copy()
        form.pop('strategy')
        configuration = submission_values(form, self.settings, self.options)
        self.assertEqual(configuration['strategy'], 'P2')
        with self.app.test_request_context('/'):
            html = render_template('workspace.html', models=[], controls={}, available=self.options,
                                   active_submission=None, form_values={})
        choices = BeautifulSoup(html, 'html.parser').select('#launchStrategy option')
        self.assertEqual([option['value'] for option in choices], ['P0','P1','P2','P3','P4','P5'])
        self.assertEqual([option['value'] for option in choices if option.has_attr('selected')], ['P2'])

    def test_only_http_urls_without_credentials_are_admitted(self):
        for value in ('file:///tmp/test.html','javascript:alert(1)','https://name:secret@example.org'):
            self.form['urls']=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                submission_values(self.form,self.settings,self.options)

    def test_empty_urls_never_fall_back_to_a_dataset(self):
        self.form['urls']='  '
        with self.assertRaises(ValueError):submission_values(self.form,self.settings,self.options)

    def test_capture_name_is_optional_and_saved_only_at_submission(self):
        for name in ('', '  Calibración UV  '):
            form = self.form.copy()
            form['capture_name'] = name
            configuration = submission_values(form,self.settings,self.options)
            conn = MagicMock()
            conn.cursor.return_value.lastrowid = 42
            with patch('workspace_pipeline.get_connection',return_value=conn),patch('result_portability.evaluation_signature',return_value='signature'):
                ident = enqueue(self.store,configuration,self.settings,'es')
            arguments = conn.cursor.return_value.execute.call_args.args[1]
            self.assertEqual(arguments[0],name.strip() or 'Capture '+ident[:8])
            self.assertEqual(self.store.get(ident)['data']['capture_name'],name.strip())

    def test_capture_name_length_is_checked_before_enqueue(self):
        self.form['capture_name'] = 'x'*161
        with self.assertRaisesRegex(ValueError,'160'):
            submission_values(self.form,self.settings,self.options)

    def test_invalid_budget_and_attempt_limits_are_rejected(self):
        for key,value in [('max_cost_usd','NaN'),('max_cost_usd','-1'),('max_cost_usd','6'),
                          ('max_iterations','0'),('max_iterations','11'),('max_execution_seconds','0'),
                          ('max_generation_attempts_per_candidate','0'),
                          ('max_generation_attempts_per_candidate','1001'),
                          ('max_generation_attempts_per_candidate','1.5')]:
            form = self.form.copy();form[key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                submission_values(form,self.settings,self.options)

    def test_attempts_per_candidate_default_and_explicit_value_reach_the_frozen_submission(self):
        self.assertEqual(submission_values(self.form, self.settings, self.options)['values']['max_generation_attempts_per_candidate'], '20')
        self.form['max_generation_attempts_per_candidate'] = '7'
        self.assertEqual(submission_values(self.form, self.settings, self.options)['values']['max_generation_attempts_per_candidate'], '7')

    def test_per_request_ceiling_matches_the_entered_url_budget(self):
        for budget in ('0.10','1','5'):
            form = self.form.copy()
            form['max_cost_usd'] = budget
            values = submission_values(form,self.settings,self.options)['values']
            self.assertEqual(float(values['harness_max_call_cost_usd']),float(budget))
            self.assertEqual(float(values['max_cost_usd']),float(budget))

    def test_unknown_policy_corpus_and_verifier_are_rejected(self):
        for key in ('strategy','harness_corpus','harness_verifier'):
            form=self.form.copy();form[key]='unknown'
            with self.subTest(key=key),self.assertRaises(ValueError):
                submission_values(form,self.settings,self.options)

    def test_zero_shot_is_single_pass_and_fixed_policies_map_to_current_levels(self):
        for policy,level in [('P0','0'),('P1','0'),('P2','1'),('P3','2'),('P4','3'),('P5','4')]:
            form=self.form.copy();form['strategy']=policy
            values=submission_values(form,self.settings,self.options)['values']
            self.assertEqual(values['preservation_level'],level)
            self.assertEqual(values['execution_mode'],'single_shot' if policy=='P0' else 'iterative')

    def test_submission_freezes_public_configuration_without_credentials(self):
        settings=dict(self.settings,openrouter_api_key='DO-NOT-STORE',remediation_model_catalog_json='[]')
        configuration=submission_values(self.form,settings,self.options)
        self.assertNotIn('DO-NOT-STORE',json.dumps(configuration))
        self.assertEqual(configuration['settings']['remediation_model_catalog_json'],'[]')

    def test_frozen_reuse_and_rag_are_independent_submission_controls(self):
        for reuse in (False, True):
            for rag in (False, True):
                form = self.form.copy()
                form.pop('act_grounding', None)
                if reuse:
                    form['reuse_cached_results'] = 'on'
                if rag:
                    form['act_grounding'] = 'on'
                with self.subTest(reuse=reuse, rag=rag):
                    configuration = submission_values(form, self.settings, self.options)
                    self.assertEqual(configuration['reuse_cached_results'], reuse)
                    self.assertEqual(configuration['values']['act_grounding'], 'on' if rag else 'off')

    def test_enqueue_uses_an_independent_total_budget_and_preserves_url_identity(self):
        configuration=submission_values(self.form,self.settings,self.options)
        conn=MagicMock();cursor=conn.cursor.return_value;cursor.lastrowid=42
        with patch('workspace_pipeline.get_connection',return_value=conn),patch('result_portability.evaluation_signature',return_value='signature'):
            ident=enqueue(self.store,configuration,self.settings,'es')
        record=self.store.get(ident)['data']
        group=json.loads(record['values']['harness_budget_json'])
        self.assertEqual(group['total_usd'],0.25)
        self.assertEqual(group['stage_limits'],{'remediation':0.25})
        self.assertEqual(record['experiment_id'],42)
        self.assertEqual(record['values']['submission_id'],ident)
        self.assertEqual(self.store.checkpoint(ident)[0]['status'],'queued')
        conn.commit.assert_called_once()

    def test_enqueue_persists_the_frozen_reuse_choice(self):
        for reuse in (False, True):
            configuration = submission_values(self.form, self.settings, self.options)
            configuration['reuse_cached_results'] = reuse
            conn = MagicMock()
            conn.cursor.return_value.lastrowid = 42
            with self.subTest(reuse=reuse), patch('workspace_pipeline.get_connection', return_value=conn), patch('result_portability.evaluation_signature', return_value='signature'):
                ident = enqueue(self.store, configuration, self.settings, 'en')
            statement, values = conn.cursor.return_value.execute.call_args.args
            self.assertIn('reuse_cached_results,evaluation_signature', statement)
            self.assertEqual(values[4:6], (reuse, 'signature'))
            self.assertEqual(self.store.get(ident)['data']['reuse_cached_results'], reuse)

    def test_database_failure_rolls_back_submission(self):
        conn=MagicMock();conn.cursor.return_value.execute.side_effect=RuntimeError('database unavailable')
        configuration=submission_values(self.form,self.settings,self.options)
        with patch('workspace_pipeline.get_connection',return_value=conn),self.assertRaises(RuntimeError):
            enqueue(self.store,configuration,self.settings,'es')
        conn.rollback.assert_called_once()
        self.assertEqual(self.store.list('url_submission'),[])

    def test_capture_must_finish_before_remediation_can_be_created(self):
        row=self.store.append('url_submission',{'experiment_id':42,'settings':{},'values':{}})
        self.store.checkpoint(row['id'],{'status':'queued'})
        conn=MagicMock();conn.cursor.return_value.fetchone.return_value={'status':'running'}
        with patch('workspace_pipeline.get_connection',return_value=conn),patch('remediation_submission.create_remediation') as create:
            self.assertFalse(advance(self.store,row['id'],self.settings))
        create.assert_not_called()

    def test_readonly_catalogue_cannot_change_checkpoints(self):
        record=self.store.append('fixture',{'value':1})
        with patch.dict('os.environ',{'HARNESS_READ_ONLY':'1'}):
            readonly=Store(self.temporary.name)
            self.assertEqual(readonly.get(record['id']),record)
            import sqlite3
            with self.assertRaises(sqlite3.OperationalError):readonly.checkpoint('x',{'status':'changed'})

    def test_existing_installation_can_enable_tasks_without_startup_backfills(self):
        environment = {'HARNESS_READ_ONLY': '0', 'HARNESS_INIT_DB': '0',
                       'SECRET_KEY': 'isolated-test-key'}
        with patch.dict('os.environ', environment), patch('main.init_db') as initialize:
            writable = create_app({'TESTING': False})
        self.assertFalse(writable.config['READ_ONLY'])
        initialize.assert_not_called()

    def test_new_installation_still_initializes_its_schema(self):
        environment = {'HARNESS_READ_ONLY': '0', 'HARNESS_INIT_DB': '1',
                       'SECRET_KEY': 'isolated-test-key'}
        with patch.dict('os.environ', environment), patch('main.init_db') as initialize:
            create_app({'TESTING': False})
        initialize.assert_called_once_with()

    def test_excluded_routes_are_absent_not_hidden(self):
        endpoints={rule.endpoint for rule in self.app.url_map.iter_rules()}
        for name in ('human_review.index','comparisons.comparisons','extension_api.submit',
                     'experiments.compose_experiment','experiments.import_experiment_json',
                     'experiments.manage_urls','components.interventions','experiments.run_experiment'):
            self.assertNotIn(name,endpoints)
        for path in ('/harness/reviews','/comparisons','/experiments/compose','/experiments/import','/urls/manage','/interventions','/acquisition/new'):
            self.assertEqual(self.app.test_client().get(path).status_code,404)

    def test_get_start_only_displays_configuration(self):
        options={'corpora':[],'verifiers':[]}
        with patch('routes.workspace.get_settings',return_value=self.settings),patch('routes.workspace.configuration_options',return_value=options),patch('routes.workspace.model_choices',return_value=[]),patch('routes.workspace.common_conditions',return_value={'cost':0.25,'axe':5,'lighthouse':90}),patch('routes.workspace.enqueue') as enqueue_mock:
            response=self.app.test_client().get('/')
        self.assertEqual(response.status_code,200)
        self.assertIn(b'Web Accessibility Harness',response.data)
        self.assertNotIn(b'app-sidebar',response.data)
        self.assertIn(b'commandMenu',response.data)
        enqueue_mock.assert_not_called()

    def test_start_requires_csrf_before_creating_a_submission(self):
        with patch('routes.workspace.get_settings',return_value=self.settings),patch('routes.workspace.configuration_options',return_value=self.options),patch('routes.workspace.enqueue') as enqueue_mock:
            self.assertEqual(self.app.test_client().post('/',data=self.form).status_code,400)
        enqueue_mock.assert_not_called()

    def test_submit_opens_the_remediation_preparation_screen(self):
        with patch('routes.workspace.get_settings', return_value=self.settings), patch('routes.workspace.configuration_options', return_value=self.options), patch('routes.workspace.protect'), patch('routes.workspace.enqueue', return_value='new-task'):
            response = self.app.test_client().post('/', data=self.form)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/remediation/preparing/new-task')

    def test_previous_session_links_go_directly_to_the_same_execution(self):
        configuration = submission_values(self.form, self.settings, self.options)
        record = self.store.append('url_submission', dict(configuration, experiment_id=42))
        self.store.checkpoint(record['id'], {'status': 'queued', 'runs': []})
        connection = MagicMock()
        connection.cursor.return_value.fetchone.return_value = {'status': 'completed'}
        connection.cursor.return_value.fetchall.return_value = [{'id': 1327, 'status': 'running'}]
        with patch('routes.workspace.get_connection', return_value=connection):
            response = self.app.test_client().get('/sessions/' + record['id'])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/remediation/1327')
        self.assertEqual(self.store.checkpoint(record['id'])[0]['status'], 'queued')

    def test_preparation_shows_activity_without_submitting_again(self):
        from bs4 import BeautifulSoup
        configuration = submission_values(self.form, self.settings, self.options)
        configuration['values']['act_grounding'] = 'off'
        record = self.store.append('url_submission', dict(configuration, experiment_id=42))
        progress = {'status': 'queued', 'phase': 'queued', 'message': 'Waiting for capture…', 'destination': None, 'runs': []}
        with patch('routes.workspace.get_settings', return_value=self.settings), patch('routes.workspace.configuration_options', return_value=self.options), patch('routes.workspace.model_choices', return_value=[]), patch('routes.workspace.common_conditions', return_value={'cost': 1, 'axe': 5, 'lighthouse': 90}), patch('routes.workspace.submission_progress', return_value=progress):
            response = self.app.test_client().get('/remediation/preparing/' + record['id'])
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'data-submission-status=', response.data)
        self.assertIn(b'https://example.org/', response.data)
        self.assertNotIn(b'Harness session', response.data)
        page = BeautifulSoup(response.data, 'html.parser')
        self.assertIsNotNone(page.select_one('.harness-loader'))
        self.assertIsNone(page.select_one('#launchForm'))
        self.assertEqual(page.select_one('[data-submission-status]')['aria-busy'], 'true')
        self.assertEqual(self.store.checkpoint(record['id'])[0], {})

    def test_batch_destination_contains_only_its_own_executions(self):
        from routes.workspace import submission_progress
        record = self.store.append('url_submission', {'experiment_id': 42,
                                  'urls': ['https://example.org/', 'https://other.org/']})
        connection = MagicMock()
        connection.cursor.return_value.fetchone.return_value = {'status': 'completed'}
        connection.cursor.return_value.fetchall.return_value = [{'id': 12, 'status': 'queued'}, {'id': 13, 'status': 'queued'}]
        with self.app.test_request_context('/'), patch('routes.workspace.get_connection', return_value=connection):
            state = submission_progress(self.store, record)
        self.assertEqual(state['destination'], '/remediation/?live_ids=12,13')
        query, values = connection.cursor.return_value.execute.call_args.args
        self.assertIn('submission_id', query)
        self.assertEqual(values, (42, record['id']))

    def test_capture_failure_is_reported_without_creating_a_remediation(self):
        from routes.workspace import submission_progress
        record = self.store.append('url_submission', {'experiment_id': 42, 'urls': ['https://example.org/']})
        connection = MagicMock()
        connection.cursor.return_value.fetchone.return_value = {'status': 'failed'}
        connection.cursor.return_value.fetchall.return_value = []
        with self.app.test_request_context('/'), patch('routes.workspace.get_connection', return_value=connection):
            state = submission_progress(self.store, record)
        self.assertEqual(state['status'], 'failed')
        self.assertIsNone(state['destination'])

    def test_configuration_is_last_navigation_entry(self):
        from navigation import NAVIGATION
        self.assertEqual(NAVIGATION[-1][0],'harness.configuration')
        self.assertNotIn('components.interventions',{name for name,label in NAVIGATION})

    def test_completed_capture_creates_one_run_and_restart_reuses_its_identity(self):
        record=self.store.append('url_submission', {'experiment_id':42,'settings':{},
            'values':{'selected_model':'worker'}})
        self.store.checkpoint(record['id'],{'status':'queued'})
        capture=MagicMock(); capture.cursor.return_value.fetchone.return_value={'status':'completed'}
        capture.cursor.return_value.fetchall.return_value=[{'id':81,'status':'completed'}]
        lookup=MagicMock();lookup.cursor.return_value.fetchone.return_value={'id':123}
        finish=MagicMock();finish.cursor.return_value.fetchall.return_value=[{'id':123,'status':'completed'}]
        with patch('workspace_pipeline.get_connection',side_effect=[capture,lookup,finish]),patch('remediation_submission.create_remediation') as create:
            self.assertTrue(advance(self.store,record['id'],self.settings))
        create.assert_not_called()
        state,_=self.store.checkpoint(record['id'])
        self.assertEqual(state['status'],'completed')
        self.assertEqual(state['runs'],[{'id':123,'status':'completed'}])

    def test_new_run_preserves_selected_model_cost_and_submission_identity(self):
        from remediation_submission import create_remediation
        from remediation_model_choices import model_choices
        from settings import SETTING_DEFAULTS, READONLY_MODEL_DEFAULTS
        settings=dict(READONLY_MODEL_DEFAULTS,**SETTING_DEFAULTS)
        model=model_choices(settings)[0]
        source=Path(self.temporary.name)/'source.html';source.write_text('<html lang="en"><body>Saved page</body></html>')
        form=MultiDict({'source_result_id':'81','selected_model':model['id'],
            'preservation_level':'0','run_limits_configured':'1','max_iterations':'3',
            'max_cost_usd':'0.25','max_execution_seconds':'360','max_axe':'5',
            'min_lighthouse':'90','submission_id':'submission-fixture'})
        conn=MagicMock();cursor=conn.cursor.return_value;cursor.lastrowid=123
        cursor.fetchone.return_value={'id':81,'url':'https://example.org/','response_source_path':str(source)}
        with self.app.app_context(),patch('remediation_submission.get_connection',return_value=conn),patch('remediation_submission.now_local',return_value='2026-01-01'),patch('requests.sessions.Session.request',side_effect=AssertionError('No provider request')):
            self.assertEqual(create_remediation(form,settings),123)
        configuration=[call.args[1][0] for call in cursor.execute.call_args_list if call.args[0].startswith('UPDATE remediation_runs SET model_config_json')][0]
        value=json.loads(configuration)
        self.assertEqual(value['submission_id'],'submission-fixture')
        self.assertEqual(value['model'],model['model'])
        insert=next(call.args[1] for call in cursor.execute.call_args_list if call.args[0].startswith('INSERT INTO remediation_runs'))
        self.assertEqual(insert[24],0.25)
        conn.commit.assert_called_once()


if __name__=='__main__':unittest.main()
