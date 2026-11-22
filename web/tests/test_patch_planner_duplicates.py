import copy
import unittest

from remediation_planner import component_candidates, validate_component_plan


class PatchPlannerDuplicateTests(unittest.TestCase):
    def setUp(self):
        self.candidates = component_candidates(
            '<body><nav id="nav">Menu</nav><main>Article</main><footer>Contact</footer></body>'
        )
        self.first = dict(id='c0', area='header', intervention='repair',
                          depends_on=[], root_cause='Contrast', reason='Repair CTA contrast.')
        self.second = dict(self.first, root_cause='Accessible name', reason='Name the search link.')

    def test_compatible_repairs_keep_all_intents_and_source_ownership(self):
        proposal = {'components': [self.first, self.second]}
        before = copy.deepcopy(proposal)
        plan = validate_component_plan(proposal, self.candidates, patch_only=True)
        self.assertEqual(proposal, before)
        self.assertEqual([r['id'] for r in plan], ['c0', 'c1', 'c2'])
        self.assertEqual([r['source'] for r in plan], [r['source'] for r in self.candidates])
        self.assertEqual(plan[0]['root_cause'], 'Contrast\nAccessible name')
        self.assertEqual(plan[0]['reason'], 'Repair CTA contrast.\nName the search link.')
        self.assertEqual([r['intervention'] for r in plan], ['repair', 'preserve', 'preserve'])

    def test_equal_explicit_dependencies_are_preserved(self):
        proposal = {'components': [dict(self.first, depends_on=['c1']),
                                   dict(self.second, depends_on=['c1'])]}
        plan = validate_component_plan(proposal, self.candidates, patch_only=True)
        self.assertEqual(plan[0]['depends_on'], ['c1'])
        self.assertEqual(plan[1]['intervention'], 'preserve')

    def test_conflicting_or_ambiguous_duplicates_remain_rejected(self):
        for change in ({'area': 'footer'}, {'intervention': 'preserve'},
                       {'intervention': 'regenerate'}, {'depends_on': ['c1']},
                       {'depends_on': ['invented']}, {'reason': {'guess': 'text'}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_component_plan(
                    {'components': [self.first, dict(self.second, **change)]},
                    self.candidates, patch_only=True,
                )

    def test_regeneration_contract_keeps_duplicate_rejection(self):
        with self.assertRaisesRegex(ValueError, 'exactly once'):
            validate_component_plan({'components': [self.first, self.second]}, self.candidates)

    def test_repeated_explanation_is_not_duplicated(self):
        proposal = {'components': [self.first, self.second, self.first, self.second]}
        plan = validate_component_plan(proposal, self.candidates, patch_only=True)
        self.assertEqual(plan[0]['root_cause'], 'Contrast\nAccessible name')
        self.assertEqual(plan[0]['reason'], 'Repair CTA contrast.\nName the search link.')

    def test_unknown_component_cannot_gain_an_assignment(self):
        with self.assertRaisesRegex(ValueError, 'known components'):
            validate_component_plan(
                {'components': [dict(self.first, id='invented'), dict(self.second, id='invented')]},
                self.candidates, patch_only=True,
            )


if __name__ == '__main__':
    unittest.main()
