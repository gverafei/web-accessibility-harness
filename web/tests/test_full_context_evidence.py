"""Restore the observed complete repair input without reverting safety fixes."""
import json
import unittest
from types import SimpleNamespace

from harness.dynamic_objectives import (
    CURRENT_EVIDENCE_VERSION, COMPACT_EVIDENCE_VERSION, COORDINATED_EVIDENCE_VERSION, SHARED_EVIDENCE_VERSION, SOURCE_BOUND_VERSION, ROLE_BOUND_VERSION,
    corrective_messages, repair_work, work_messages,
)
from test_role_scoped_evidence import evidence


class FullContextEvidenceTests(unittest.TestCase):
    def test_general_focus_matches_the_complete_historical_worker_addendum(self):
        data = evidence()
        work = repair_work(data, {'patch_failures': [{}]},
            {'focus': 'all', 'target_types': ['link-name']}, version=CURRENT_EVIDENCE_VERSION)
        for role in ('component-planner', 'patch-generator'):
            self.assertEqual(work_messages(work, role), corrective_messages(data))
        self.assertEqual(work['active_contextual_evidence'], data)
        self.assertEqual(work['deferred_failed_findings'], 0)
        self.assertIn('content content', work_messages(work)[1]['content'])

    def test_explicit_category_still_filters_findings_without_changing_measurements(self):
        work = repair_work(evidence(), {'patch_failures': [{}]},
            {'focus': 'Semantic', 'target_types': ['landmark-purpose-mismatch']},
            version=CURRENT_EVIDENCE_VERSION)
        messages = work_messages(work, 'component-planner')
        actual = json.loads(messages[1]['content'].split('\n', 1)[1])
        self.assertEqual([r['opportunity_id'] for r in actual['failed_opportunities']], ['sem'])
        self.assertEqual(actual['taxonomy_failed'], evidence()['taxonomy_failed'])
        self.assertIn('selected focus is Semantic', messages[0]['content'])
        self.assertEqual(work['deferred_failed_findings'], 1)
