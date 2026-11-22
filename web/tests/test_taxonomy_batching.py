import unittest
from accessibility_taxonomy.assessment import review_batches

class ModalityBatchTests(unittest.TestCase):
    def test_alternating_evidence_does_not_force_single_case_calls(self):
        rows=[{'opportunity_id':str(i)} for i in range(240)]
        images={str(i):object() for i in range(0,240,2)}
        batches=review_batches(rows,images)
        self.assertEqual(len(batches),36)  # six text batches + thirty visual batches
        self.assertEqual(len({r['opportunity_id'] for b in batches for r in b}),240)
        self.assertEqual([r['opportunity_id'] for b in batches[:6] for r in b],[str(i) for i in range(1,240,2)])
        for b in batches:
            visual=[r['opportunity_id'] in images for r in b]
            self.assertTrue(all(visual) or not any(visual))
            self.assertLessEqual(len(b),4 if all(visual) else 20)
        self.assertEqual(rows[0],{'opportunity_id':'0'})
