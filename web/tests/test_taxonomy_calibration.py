import unittest
from accessibility_taxonomy.calibration import controls,score

class CalibrationBankTests(unittest.TestCase):
    def test_declared_scope_and_replicates(self):
        bank=controls()
        self.assertEqual(len(bank),24)
        self.assertEqual(len({r['opportunity']['type'] for r in bank}),8)
        expected={r['id']:r['expected'] for r in bank}
        self.assertTrue(score(bank,[expected,expected])['gate_passed'])
        wrong=dict(expected);wrong[bank[0]['id']]='failed'
        self.assertFalse(score(bank,[expected,wrong])['gate_passed'])
        self.assertFalse(score(bank,[expected])['gate_passed'])

class RelationalCalibrationEvidenceTests(unittest.TestCase):
    def test_table_controls_identify_cells_and_independent_headers(self):
        from accessibility_taxonomy.calibration import relational_controls
        from accessibility_taxonomy.inventory import inventory
        for heldout in (False, True):
            bank=relational_controls(heldout)
            self.assertEqual(len(bank),20)
            self.assertEqual(len({x['id'] for x in bank}),20)
            table=[x for x in bank if x['type']=='table-header-association-mismatch']
            for item in table:
                rows=inventory(item['html'],{},'https://controls.invalid/')['opportunities']
                matches=[r for r in rows if r['type']==item['type'] and
                         (not item.get('target_tag') or r['context']['element']['tag']==item['target_tag']) and
                         (not item.get('target_id') or r['context']['element']['attributes'].get('id')==item['target_id'])]
                self.assertEqual(len(matches),1)
                if item.get('target_tag'):
                    self.assertEqual(matches[0]['context']['element']['tag'],'td')
                else:
                    self.assertEqual(matches[0]['context']['element']['tag'],'th')
            self.assertEqual(len(table),5)

    def test_native_state_controls_require_a_bound_rendered_witness(self):
        from accessibility_taxonomy.calibration import relational_controls
        from accessibility_taxonomy.inventory import inventory
        from accessibility_taxonomy import RUBRICS
        from accessibility_taxonomy.semantic_context import RELATIONAL
        bank=relational_controls()
        self.assertEqual({r['type'] for r in bank},RELATIONAL)
        for item in bank:
            self.assertTrue(RUBRICS[item['type']])
            if item['type']=='aria-state-mismatch':
                row=next(r for r in inventory(item['html'],{},'https://controls.invalid/')['opportunities'] if r['type']==item['type'])
                self.assertNotIn('rendered_observation',row['context']['observed_purpose'])
