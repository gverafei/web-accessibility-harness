import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask
from capture_saved_page import bound_capture
from harness.store import Store
from routes.experiments import experiments_bp


class SavedCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.results = self.root / 'results'
        self.results.mkdir()
        self.source = self.results / 'source.html'
        self.source.write_text('<html><body>Frozen acquisition</body></html>')
        self.image = self.results / 'capture.jpg'
        self.image.write_bytes(b'captured image')
        self.store = Store(self.root / 'catalogue')
        html = self.store.blob(self.source.read_bytes(),'rendered','fixture','text/html')
        screenshot = self.store.blob(self.image.read_bytes(),'screenshot','fixture','image/jpeg')
        self.capture = self.store.append('capture',{'rendered_id':html['id'],'replay_source_id':html['id'],
            'screenshot_id':screenshot['id'],'screenshot_path':str(self.image),
            'captured_url':'https://example.test/','assets':[],'scope':'Saved acquisition fixture'},'fixture')
        self.row = {'id':502,'experiment_id':475,'url':'https://example.test/',
                    'source_snapshot_path':str(self.source),'screenshot_path':str(self.image)}
        self.app = Flask(__name__)
        self.app.config.update(HARNESS_ROOT=str(self.store.root),TESTING=True)
        self.app.register_blueprint(experiments_bp)
        self.client = self.app.test_client()

    def open_page(self, row=None):
        connection = Mock()
        connection.cursor.return_value.fetchone.return_value = row or self.row
        with patch('routes.experiments.get_connection',return_value=connection), \
             patch('capture_saved_page.RESULTS_ROOT',self.results), \
             patch.dict('os.environ',{'DATASET_ROOT':str(self.root/'datasets')}):
            return self.client.get('/experiments/475/source/502')

    def test_saved_page_uses_bound_resources_and_preserves_canonical_evidence(self):
        before = self.source.read_bytes(),self.image.read_bytes(),self.store.get(self.capture['id'])['hash']
        response = self.open_page()
        self.assertEqual(response.status_code,302)
        self.assertIn('/experiments/475/source/502/saved/',response.location)
        with patch.dict('os.environ',{'DATASET_ROOT':str(self.root/'datasets')}), \
             patch('requests.get',return_value=Mock(status_code=200,content=b'<html>Wrong transport bytes</html>',
                                                   headers={'Content-Type':'text/html'})) as request:
            # The hash check rejects a transport entity differing from the derived page.
            rejected = self.client.get(response.location)
            self.assertEqual(rejected.status_code,409)
            self.assertTrue(request.call_args.args[0].startswith('http://dataset-server:8080/captures/502/'))
            cached = next((self.root/'datasets/captures/502/.saved').glob('*/'+self.capture['id']+'/page.html'))
            request.return_value.content = cached.read_bytes()
            served = self.client.get(response.location)
            self.assertEqual(served.status_code,200)
            self.assertIn('sandbox',served.headers['Content-Security-Policy'])
            self.assertNotIn('allow-same-origin',served.headers['Content-Security-Policy'])
        self.assertEqual(before,(self.source.read_bytes(),self.image.read_bytes(),self.store.get(self.capture['id'])['hash']))

    def test_same_url_with_changed_source_or_screenshot_is_not_a_binding(self):
        self.assertEqual(bound_capture(self.store,self.row,self.results)['id'],self.capture['id'])
        self.source.write_text('<html><body>Different acquisition</body></html>')
        self.assertIsNone(bound_capture(self.store,self.row,self.results))
        self.assertEqual(self.open_page().status_code,404)

    def test_environment_catalogue_is_used_when_app_configuration_is_unset(self):
        self.app.config.pop('HARNESS_ROOT')
        with patch.dict('os.environ',{'HARNESS_ROOT':str(self.store.root)}):
            self.assertEqual(self.open_page().status_code,302)

    def test_previous_display_url_redirects_to_the_current_adapter(self):
        response = self.open_page()
        receipt = next((self.root/'datasets/captures/502/.saved').glob('*/navigation.json'))
        data = json.loads(receipt.read_text())
        data['version'] = 'saved-capture-navigation-v1'
        receipt.write_text(json.dumps(data))
        with patch.dict('os.environ',{'DATASET_ROOT':str(self.root/'datasets')}),patch('requests.get') as request:
            response = self.client.get(response.location)
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.location,'/experiments/475/source/502')
        request.assert_not_called()

    def test_changed_adapter_signature_refreshes_an_existing_display_link(self):
        response = self.open_page()
        with patch.dict('os.environ',{'DATASET_ROOT':str(self.root/'datasets')}), \
             patch('capture_saved_page.presentation_signature',return_value='updated-adapter'), \
             patch('requests.get') as request:
            refreshed = self.client.get(response.location)
        self.assertEqual(refreshed.status_code,302)
        self.assertEqual(refreshed.location,'/experiments/475/source/502')
        request.assert_not_called()

    def test_other_experiment_and_traversal_cannot_read_saved_files(self):
        response = self.open_page()
        wrong_experiment = response.location.replace('/experiments/475/','/experiments/476/')
        with patch.dict('os.environ',{'DATASET_ROOT':str(self.root/'datasets')}),patch('requests.get') as request:
            self.assertEqual(self.client.get(wrong_experiment).status_code,404)
            self.assertEqual(self.client.get(response.location.replace('page.html','../navigation.json')).status_code,404)
            request.assert_not_called()
