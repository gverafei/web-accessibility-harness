import unittest
from harness.replay_admission import compare
class VisibilityReferenceTests(unittest.TestCase):
 def test_old_reference_cannot_be_silently_reclassified_as_current(self):
  original={'text':'Example content','controls':[],'visible_images':0}
  replay={**original,'visibility_version':'reachable-document-regions-v1'}
  result=compare(original,replay)
  self.assertEqual(result['status'],'review_required')
  self.assertEqual(result['reasons'],['incompatible_visible_evidence_policy'])
  self.assertNotEqual(compare({**original,'visibility_version':replay['visibility_version']},replay)['reasons'],result['reasons'])
