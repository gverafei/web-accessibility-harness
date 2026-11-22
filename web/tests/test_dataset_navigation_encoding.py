import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask
from dataset_navigation import serve_dataset_file


class SavedPageEncoding(unittest.TestCase):
    def test_saved_utf8_text_without_metadata_keeps_glyphs_and_exact_bytes(self):
        app = Flask(__name__)
        samples = [
            ('page.html', 'text/html', '<button>\uf618</button>© ♥'.encode()),
            ('icons.css', 'text/css', '.icon::before{content:"\uf618"}'.encode()),
            ('latin.html', 'text/html', '<p>café</p>'.encode('latin-1')),
            ('declared.html', 'text/html; charset=iso-8859-1', b'<p>ASCII</p>'),
            ('font.woff2', 'font/woff2', b'wOF2'),
        ]
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'saved'
            directory.mkdir()
            for filename, media_type, raw in samples:
                with self.subTest(filename=filename):
                    (directory / filename).write_bytes(raw)
                    with app.test_request_context(), patch('requests.get', return_value=Mock(
                            status_code=200, content=raw, headers={'Content-Type': media_type})):
                        result = serve_dataset_file(directory, filename, root)
                    self.assertEqual(result.data, raw)
                    expected = media_type + '; charset=utf-8' if filename in ('page.html', 'icons.css') else media_type
                    self.assertEqual(result.headers['Content-Type'], expected)
                    self.assertNotIn('allow-same-origin', result.headers['Content-Security-Policy'])

    def test_saved_media_ranges_keep_original_bytes_sandbox_and_anonymous_asset_scope(self):
        import hashlib
        app=Flask(__name__)
        raw=b'0123456789'
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)/'saved';(directory/'assets').mkdir(parents=True)
            (directory/'assets'/'clip').write_bytes(raw)
            upstream=Mock(status_code=200,content=raw,headers={'Content-Type':'video/mp4'})
            for value,status,body,content_range in [
                ('bytes=0-3',206,b'0123','bytes 0-3/10'),('bytes=6-',206,b'6789','bytes 6-9/10'),
                ('bytes=-2',206,b'89','bytes 8-9/10'),('bytes=20-',416,b'','bytes */10'),
                ('bytes=0-1,4-5',416,b'','bytes */10'),('invalid',416,b'','bytes */10')]:
                with self.subTest(value=value), app.test_request_context(headers={'Range':value}), patch('requests.get',return_value=upstream):
                    response=serve_dataset_file(directory,'assets/clip',root,hashlib.sha256(raw).hexdigest(),anonymous_resource=True)
                self.assertEqual(response.status_code,status)
                self.assertEqual(response.data,body)
                self.assertEqual(response.headers['Content-Range'],content_range)
                self.assertEqual(response.headers['Access-Control-Allow-Origin'],'*')
                self.assertEqual(response.headers['Accept-Ranges'],'bytes')
                self.assertNotIn('allow-same-origin',response.headers['Content-Security-Policy'])
            with app.test_request_context(headers={'Range':'bytes=0-1'}), patch('requests.get',return_value=upstream):
                self.assertEqual(serve_dataset_file(directory,'assets/clip',root,'a'*64).status_code,409)
            self.assertEqual((directory/'assets'/'clip').read_bytes(),raw)
