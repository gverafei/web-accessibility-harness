"""Planner compression must preserve every measured finding and its exact text."""
import copy
import json
import unittest
from harness.planning_evidence import shared_feedback


class PlanningEvidenceTests(unittest.TestCase):
    def restore(self, encoded):
        if encoded.get('encoding') != 'shared-planning-evidence-v1':
            return encoded
        pool = encoded['evidence_text_pool']

        def decode(value):
            if isinstance(value, dict) and set(value) == {'evidence_text_parts'}:
                return ''.join(part if isinstance(part, str) else pool[part['text_ref']]
                               for part in value['evidence_text_parts'])
            if isinstance(value, dict):
                return {key: decode(child) for key, child in value.items()}
            if isinstance(value, list):
                return [decode(child) for child in value]
            return value
        return decode(encoded['findings'])

    def test_all_findings_and_unicode_survive_shared_long_page_text(self):
        page = 'Página completa 🌓 con enlaces, imágenes y controles. ' * 700
        original = {'failed_opportunities': [
            {'type': kind, 'identity': index, 'context': {'observed_text': page + str(index)}}
            for index, kind in enumerate(['heading', 'link', 'button'])],
            'remaining_taxonomy_failures': {'Semantic': 3}, 'coverage': .97}
        untouched = copy.deepcopy(original)
        encoded = shared_feedback(original)
        self.assertEqual(self.restore(encoded), original)
        self.assertEqual(original, untouched)
        self.assertLess(len(json.dumps(encoded)), len(json.dumps(original)) / 2)

    def test_unique_evidence_is_not_summarized_or_truncated(self):
        original = {'findings': [{'context': 'x' * 511}, {'context': 'y' * 511}],
                    'unresolved': [], 'status': 'failed'}
        self.assertEqual(shared_feedback(original), original)
        self.assertEqual(self.restore(shared_feedback(original)), original)
