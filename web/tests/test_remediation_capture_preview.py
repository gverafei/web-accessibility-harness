import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from remediation_capture_preview import refreshed_capture, refreshed_evidence_capture


class CapturePreviewTests(unittest.TestCase):
    def test_preview_requires_unchanged_candidate_original_and_refreshed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'candidate.html'; original=root/'original.jpg'; image=root/'display.jpg'
            source.write_bytes(b'<main>Same candidate</main>'); original.write_bytes(b'original'); image.write_bytes(b'refreshed')
            sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
            entry={'source_sha256':sha(source),'original_capture_sha256':sha(original),
                   'capture_sha256':sha(image),'path':'display.jpg'}
            manifest=root/'.capture-previews.json'
            manifest.write_text(json.dumps({'version':'local-capture-preview-v1','iterations':{'2110':entry}}))
            self.assertEqual(refreshed_capture(root,2110,source,original,root),image)
            self.assertEqual(refreshed_evidence_capture(root, source.read_bytes(), original.read_bytes(), root), image)
            self.assertIsNone(refreshed_evidence_capture(root, b'other candidate', original.read_bytes(), root))
            self.assertIsNone(refreshed_evidence_capture(root, source.read_bytes(), b'other original capture', root))
            self.assertIsNone(refreshed_capture(root,2112,source,original,root))
            for target in(source,original,image):
                saved=target.read_bytes();target.write_bytes(b'changed')
                self.assertIsNone(refreshed_capture(root,2110,source,original,root));target.write_bytes(saved)
            entry['path']='../outside.jpg'
            manifest.write_text(json.dumps({'version':'local-capture-preview-v1','iterations':{'2110':entry}}))
            self.assertIsNone(refreshed_capture(root,2110,source,original,root))
            self.assertIsNone(refreshed_evidence_capture(root, source.read_bytes(), original.read_bytes(), root))

    def test_review_preview_rejects_ambiguous_bindings_and_changed_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / 'display.jpg'
            image.write_bytes(b'refreshed')
            entry = {'source_sha256': hashlib.sha256(b'candidate').hexdigest(),
                     'original_capture_sha256': hashlib.sha256(b'original').hexdigest(),
                     'capture_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                     'path': image.name}
            manifest = root / '.capture-previews.json'
            entries = {'1': entry, '3': dict(entry)}
            manifest.write_text(json.dumps({'version': 'local-capture-preview-v1', 'iterations': entries}))
            self.assertIsNone(refreshed_evidence_capture(root, b'candidate', b'original', root))
            del entries['3']
            manifest.write_text(json.dumps({'version': 'local-capture-preview-v1', 'iterations': entries}))
            image.write_bytes(b'changed')
            self.assertIsNone(refreshed_evidence_capture(root, b'candidate', b'original', root))
