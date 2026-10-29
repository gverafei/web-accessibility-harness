"""Native-download feedback cannot buffer streams or alter export data."""
import unittest

from bs4 import BeautifulSoup
from flask import Flask, Response, render_template, request

from download_feedback import signal_download_ready
from main import app


TOKEN = 'ab' * 16


class DownloadFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.after_request(signal_download_ready)
        self.app.add_url_rule('/file', endpoint='file', view_func=lambda: Response(
            b'original file bytes', headers={'Content-Disposition': 'attachment; filename="axe.json"'}))
        self.app.add_url_rule('/batch', endpoint='remediation.export_runs', methods=['POST'],
                              view_func=lambda: Response(b'archive', headers={'Content-Disposition': 'attachment; filename="batch.warp"'}))
        self.app.add_url_rule('/error', endpoint='error', view_func=lambda: Response('Missing', status=404))
        self.app.add_url_rule('/redirect', endpoint='redirect', view_func=lambda: Response(status=302, headers={'Location':'/error'}))
        self.app.add_url_rule('/page', endpoint='page', view_func=lambda: Response('<h1>Page</h1>'))

    def test_attachment_signals_ready_without_changing_bytes_or_filename(self):
        response = self.app.test_client().get('/file', query_string={'_download_token': TOKEN})
        self.assertEqual(response.data, b'original file bytes')
        self.assertEqual(response.headers['Content-Disposition'], 'attachment; filename="axe.json"')
        cookie = response.headers['Set-Cookie']
        self.assertIn(f'warp_download_{TOKEN}=ready', cookie)
        for attribute in ('Max-Age=60', 'Path=/', 'SameSite=Lax'):
            self.assertIn(attribute, cookie)
        self.assertNotIn('HttpOnly', cookie)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_batch_form_and_https_cookie(self):
        response = self.app.test_client().post('/batch', data={'run_ids':'806', '_download_token':TOKEN}, base_url='https://localhost')
        self.assertEqual(response.data, b'archive')
        self.assertIn('=ready', response.headers['Set-Cookie'])
        self.assertIn('Secure', response.headers['Set-Cookie'])

    def test_errors_redirects_and_nonattachments_release_control_but_never_signal_ready(self):
        for path in ('/error', '/redirect', '/page'):
            response = self.app.test_client().get(path, query_string={'_download_token':TOKEN})
            self.assertIn(f'warp_download_{TOKEN}=error', response.headers['Set-Cookie'])

    def test_absent_and_invalid_tokens_do_not_add_cookie_or_change_response(self):
        for token in ('', 'bad', 'a'*31, 'a'*33, 'A'*32, '../../secret'):
            response = self.app.test_client().get('/file', query_string={'_download_token':token})
            self.assertNotIn('Set-Cookie', response.headers)
            self.assertNotIn('Cache-Control', response.headers)

    def test_hook_does_not_consume_stream_to_signal_readiness(self):
        consumed = []
        def chunks():
            consumed.append(True)
            yield b'streamed bytes'
        with self.app.test_request_context('/file?_download_token='+TOKEN):
            response = Response(chunks(), headers={'Content-Disposition':'attachment; filename="large.warp"'})
            signal_download_ready(response)
            self.assertEqual(consumed, [])
            self.assertTrue(response.is_streamed)
            response.close()


    def test_unrelated_oversize_post_does_not_parse_form_in_feedback_hook(self):
        self.app.config['MAX_CONTENT_LENGTH'] = 1
        with self.app.test_request_context('/unrelated', method='POST', data={'large':'payload'}):
            response = signal_download_ready(Response('error', status=413))
            self.assertEqual(response.status_code, 413)
            self.assertNotIn('Set-Cookie', response.headers)

    def test_oversize_batch_post_retains_413_without_after_request_exception(self):
        self.app.config['MAX_CONTENT_LENGTH'] = 1
        def parse_batch():
            request.form.get('run_ids')
            return Response('unused')
        self.app.view_functions['remediation.export_runs'] = parse_batch
        response = self.app.test_client().post('/batch', data={'_download_token':TOKEN})
        self.assertEqual(response.status_code, 413)
        self.assertNotIn('Set-Cookie', response.headers)
