"""CSS in an explanation must not absorb the model's complete JSON plan."""
import unittest
from remediation_outputs import parse_json_response


class FencedPlanSyntaxTests(unittest.TestCase):
    def test_single_surplus_closing_brace_preserves_every_plan_field(self):
        plan = '{"components":[{"id":"c1","depends_on":[]}],"rationale":"Keep the region"}'
        response = '```json\n' + plan + '\n}\n```'
        self.assertEqual(parse_json_response(response), parse_json_response(plan))
        self.assertEqual(response, '```json\n' + plan + '\n}\n```')

    def test_surplus_brace_recovery_does_not_accept_other_data_or_truncation(self):
        for body in ('{"components":[]', '{"components":[]} {"components":["other"]}',
                     '{"components":[]} } }', '{"components":[]} ]', '{"components":[]} more'):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_json_response('```json\n' + body + '\n```')


class JsonPlanExtractionTests(unittest.TestCase):
    plan = '{"operations":[{"action":"append_css","selector":".fine","css":".fine { color: #444; }"}],"rationale":"Keep its text."}'

    def test_fenced_plan_after_css_prose_is_extracted_without_changing_operations(self):
        response = 'The inherited rule .ai p{color:#ddd} wins.\n```json\n'+self.plan+'\n```'
        self.assertEqual(parse_json_response(response), parse_json_response(self.plan))

    def test_unfenced_complete_plan_is_not_confused_with_css_or_nested_operation_objects(self):
        response = 'The rule .ai p{color:#ddd} wins.\n'+self.plan+'\nDone.'
        self.assertEqual(parse_json_response(response), parse_json_response(self.plan))
        self.assertEqual(parse_json_response(self.plan+'\nDone.'), parse_json_response(self.plan))

    def test_multiple_disjoint_objects_or_fenced_plans_are_rejected(self):
        for response in [self.plan+'\n'+self.plan, '```json\n'+self.plan+'\n```\n```json\n'+self.plan+'\n```']:
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_json_response(response)

    def test_incomplete_non_json_or_wrong_top_level_is_not_repaired(self):
        for response in ['{"operations":[', "{'operations': []}", '[{"operations":[]}]', '```json\n{"operations":[\n```', '{"operations":[{"action":"append_css"}]', 'Plan follows. {"operations":[{"action":"append_css"}]']:
            with self.subTest(response=response), self.assertRaises(ValueError):
                parse_json_response(response)
