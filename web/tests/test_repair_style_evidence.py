"""Rendered styles must not be confused with successful CSS application."""
import copy
import json
import unittest

from harness.repair_style_evidence import VERSION, observed_repairs
from harness.dynamic_objectives import repair_work, work_messages


class RepairStyleEvidenceTests(unittest.TestCase):
    source = ('<html><head><style data-warp-repair="true">'
              '#text {color:#666666}</style></head><body>'
              '<p id="text">Read</p><p id="other">Other</p></body></html>')

    def audit(self, target='#text', color='rgb(119, 119, 119)'):
        return {'patch_failures': [{'nodes': [{
            'target': [target], 'computed_style': {'color': color},
            'failure': 'Insufficient contrast'}]}]}

    def test_declared_and_observed_values_remain_separate(self):
        audit = self.audit()
        before = copy.deepcopy(audit)
        rows = observed_repairs(self.source, audit)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['present_repair_rules'], ['#text {color:#666666}'])
        self.assertEqual(rows[0]['observed_computed_style']['color'], 'rgb(119, 119, 119)')
        self.assertEqual(audit, before)
        self.assertNotIn('winning_rule', rows[0])

    def test_unknown_ambiguous_unrelated_and_nested_targets_are_not_linked(self):
        for selector in ('p', '#absent', '#other', '[invalid'):
            self.assertEqual(observed_repairs(self.source, self.audit(selector)), [])
        audit = self.audit()
        audit['patch_failures'][0]['nodes'][0]['target'] = [['iframe', '#text']]
        self.assertEqual(observed_repairs(self.source, audit), [])
        audit = self.audit()
        del audit['patch_failures'][0]['nodes'][0]['computed_style']
        self.assertEqual(observed_repairs(self.source, audit), [])
        self.assertEqual(observed_repairs(None, self.audit()), [])

    def test_only_current_applied_repair_rules_are_reported(self):
        for source in (
            self.source.replace(' data-warp-repair="true"', ''),
            self.source.replace('#text {color:#666666}', '@media print {#text {color:#666666}}'),
            '<p id="text">Read</p>',
        ):
            self.assertEqual(observed_repairs(source, self.audit()), [])

    def test_matching_computed_color_is_evidence_not_a_passed_judgment(self):
        row = observed_repairs(self.source, self.audit(color='rgb(102, 102, 102)'))[0]
        self.assertEqual(row['measured_failure'], 'Insufficient contrast')
        self.assertNotIn('passed', row)

    def test_evidence_is_visible_to_each_role_without_changing_its_output_contract(self):
        evidence = {'failed_opportunities': [{'type':'color-contrast','target':['#text']}]}
        work = repair_work(evidence, self.audit(), version=VERSION, editable_source=self.source)
        for role in ('component-planner', 'repair-generator', 'repair-diagnostician'):
            messages = work_messages(work, role)
            payload = json.loads(messages[1]['content'].split('\n', 1)[1])
            self.assertEqual(payload['applied_style_evidence'], observed_repairs(self.source, self.audit()))
            self.assertIn('specificity', messages[0]['content'])
            self.assertIn(role.split('-')[-1].upper()[:4], messages[-1]['content'])

    def test_historical_contracts_do_not_receive_new_advice(self):
        from harness.dynamic_objectives import SUPPORTED_EVIDENCE_VERSIONS
        evidence = {'failed_opportunities':[{'type':'color-contrast','target':['#text']}]}
        for version in SUPPORTED_EVIDENCE_VERSIONS:
            if version == VERSION:
                continue
            work = repair_work(evidence, self.audit(), version=version, editable_source=self.source)
            self.assertNotIn('applied_style_evidence', work)
            self.assertNotIn('applied_style_evidence', json.dumps(work_messages(work, 'repair-generator')))
