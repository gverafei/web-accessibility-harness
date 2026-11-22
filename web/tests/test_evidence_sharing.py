"""Lossless compact messages keep selectors, uncertainty and non-Latin text."""
import copy
import unittest

from harness.contracts import canonical
from harness.evidence_sharing import shared_values, VERSION
from harness.planning_evidence import expanded_feedback
from harness.dynamic_objectives import repair_work, work_messages, SHARED_EVIDENCE_VERSION


class EvidenceSharingTests(unittest.TestCase):
    def test_repeated_nested_markup_round_trip_with_distinct_targets(self):
        markup = '<a href="https://example.org/a"><img src="data:image/png;base64,' + 'abcd'*100 + '">リンク</a>'
        data = {'failed_opportunities': [
            {'type': 'link-name', 'target': ['#a'+str(i)], 'identity_basis': str(i),
             'context': {'html': markup, 'attributes': {'href': 'https://example.org/a'}}}
            for i in range(20)], 'unresolved_prior_findings': [{'status': 'unmatched', 'html': markup}]}
        before = copy.deepcopy(data)
        encoded = shared_values(data)
        self.assertEqual(encoded['encoding'], VERSION)
        self.assertEqual(expanded_feedback(encoded), data)
        self.assertLess(len(canonical(encoded)), len(canonical(data)))
        self.assertEqual(data, before)
        work = repair_work(data, {'patch_failures': [{}]}, version=SHARED_EVIDENCE_VERSION)
        self.assertEqual(work_messages(work, 'component-planner'), work_messages(work, 'patch-generator'))
        self.assertIn('Prioritize the measured Axe/Lighthouse', work_messages(work)[0]['content'])

    def test_literal_marker_objects_and_nested_strings_remain_data(self):
        data = {'rows': [{'evidence_value_ref': 'arbitrary'},
                         {'evidence_literal': {'key': 'x'*200}},
                         {'evidence_text_parts': ['text', {'evidence_value_ref': 'not-in-pool'}]}]*10}
        self.assertEqual(expanded_feedback(shared_values(data)), data)

    def test_small_unique_payload_is_not_inflated(self):
        data = {'target': ['#a'], 'status': 'unmatched'}
        self.assertEqual(shared_values(data), data)

    def test_route_planner_references_all_markup_but_keeps_finding_metadata(self):
        from harness.planning_evidence import planner_context
        from harness.dynamic_objectives import COORDINATED_EVIDENCE_VERSION
        html = '<a href="/known">Read</a>'
        context = {'state': {'measured_feedback': {'contextual_findings': {
            'failed_opportunities': [{'opportunity_id': 'id', 'status': 'failed',
                'target': ['#a'], 'type': 'link-name', 'context': {
                    'container_html': html, 'link_html': html, 'element_html': html,
                    'attributes': {'href': '/known'}, 'observed_text': 'Read'}}],
            'unresolved_prior_findings': [{'status': 'unmatched'}]}}}}
        old = expanded_feedback(planner_context(context,
            evidence_version=COORDINATED_EVIDENCE_VERSION)['state']['measured_feedback'])
        new = expanded_feedback(planner_context(context,
            evidence_version=SHARED_EVIDENCE_VERSION)['state']['measured_feedback'])
        prior = old['contextual_findings']['failed_opportunities'][0]
        row = new['contextual_findings']['failed_opportunities'][0]
        self.assertEqual(prior['context']['container_html'], html)
        self.assertNotIn('container_html', row['context'])
        self.assertEqual(row['context']['container_html_reference']['characters'], len(html))
        self.assertEqual(row['context']['attributes'], prior['context']['attributes'])
        for field in ('opportunity_id', 'status', 'target', 'type'):
            self.assertEqual(row[field], prior[field])
        self.assertEqual(new['contextual_findings']['unresolved_prior_findings'],
                         context['state']['measured_feedback']['contextual_findings']['unresolved_prior_findings'])
