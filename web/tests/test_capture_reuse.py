import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock

from harness.environment import Environment
from harness.store import Store
from result_portability import copy_artifacts


class CaptureReuseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = self.root / 'raw'
        self.original = self.raw / 'experiment_1'
        self.original.mkdir(parents=True)
        self.html = '<html><body><main>Saved page</main></body></html>'
        self.native = {'version': 'observed-native-control-state-v1', 'records': []}
        self.package = {'version': 'native-resource-package-v4',
                        'requested_url': 'https://example.org/',
                        'captured_url': 'https://example.org/',
                        'network': self.html, 'rendered': self.html,
                        'assets': [], 'visible': {}, 'native_control_reference': self.native}
        self.source = dict(id=11)
        for column, filename, body in (
                ('source_snapshot_path', 'source.html', self.html.encode()),
                ('response_source_path', 'response.html', self.html.encode()),
                ('screenshot_path', 'page.jpg', b'synthetic snapshot')):
            file = self.original / filename
            file.write_bytes(body)
            self.source[column] = str(file)
        self.snapshot = Path(self.source['screenshot_path'])
        self.package_bytes = json.dumps(self.package).encode()
        Path(str(self.snapshot) + '.resources.json').write_bytes(self.package_bytes)
        segment = self.original / 'segment.jpg'
        segment.write_bytes(b'synthetic viewport segment')
        self.descriptor = {'version': 'desktop-segments-v1', 'complete': True,
                           'segments': [{'path': str(segment), 'index': 0}]}
        Path(str(self.snapshot) + '.segments.json').write_text(json.dumps(self.descriptor))

    def test_reused_capture_remains_self_contained_after_original_files_are_removed(self):
        reused = copy_artifacts(self.source, 2, raw_root=self.raw)
        snapshot = reused['screenshot_path']
        self.assertEqual(Path(snapshot + '.resources.json').read_bytes(), self.package_bytes)
        descriptor = json.loads(Path(snapshot + '.segments.json').read_bytes())
        segment = Path(descriptor['segments'][0]['path'])
        self.assertEqual(segment.parent, Path(snapshot).parent)
        self.assertEqual(segment.read_bytes(), b'synthetic viewport segment')
        self.assertEqual(json.loads(Path(str(self.snapshot) + '.segments.json').read_bytes()),
                         self.descriptor)
        shutil.rmtree(self.original)

        store = Store(self.root / 'store')
        session = Mock()
        environment = Environment(store, session=session, results=self.raw)
        capture = environment.freeze_source('http://local/source.html', 'https://example.org/',
                                            self.html, self.html, snapshot, 'campaign', 'capture')
        self.assertEqual(capture['data']['native_control_reference'], self.native)
        self.assertEqual(store.read_blob(capture['data']['rendered_id']), self.html.encode())
        self.assertEqual(store.read_blob(capture['data']['screenshot_segments']['segments'][0]['artifact_id']),
                         b'synthetic viewport segment')
        self.assertEqual(session.mock_calls, [])

    def test_legacy_capture_without_associated_evidence_is_copied_without_inventing_it(self):
        Path(str(self.snapshot) + '.resources.json').unlink()
        Path(str(self.snapshot) + '.segments.json').unlink()
        reused = copy_artifacts(self.source, 2, raw_root=self.raw)
        self.assertEqual(Path(reused['screenshot_path']).read_bytes(), self.snapshot.read_bytes())
        self.assertFalse(Path(reused['screenshot_path'] + '.resources.json').exists())

    def test_segment_outside_the_capture_store_is_rejected(self):
        outside = self.root / 'private.txt'
        outside.write_text('private fixture')
        self.descriptor['segments'][0]['path'] = str(outside)
        Path(str(self.snapshot) + '.segments.json').write_text(json.dumps(self.descriptor))
        with self.assertRaisesRegex(ValueError, 'within the results directory'):
            copy_artifacts(self.source, 2, raw_root=self.raw)
        self.assertFalse(any(path.read_bytes() == b'private fixture'
                             for path in (self.raw / 'experiment_2').iterdir() if path.is_file()))

    def test_each_reuse_keeps_its_own_associated_evidence(self):
        first = copy_artifacts(self.source, 2, raw_root=self.raw)
        second = copy_artifacts(self.source, 2, raw_root=self.raw)
        self.assertNotEqual(first['screenshot_path'], second['screenshot_path'])
        for reused in (first, second):
            self.assertEqual(Path(reused['screenshot_path'] + '.resources.json').read_bytes(),
                             self.package_bytes)
