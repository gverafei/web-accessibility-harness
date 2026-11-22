import unittest

from remediation_recipes import automatic_recipe, common_conditions, COMMON_CONDITIONS


class RecipeTests(unittest.TestCase):
    def test_resource_overrides_apply_per_run_across_all_levels(self):
        settings = {'remediation_max_iterations': '5',
                    'remediation_max_cost_usd': '0.07',
                    'remediation_max_execution_seconds': '410'}
        for priority in (15, 35, 55, 75, 90):
            for mode in ('iterative', 'regenerate_refine', 'single_shot', 'regenerate_only'):
                with self.subTest(priority=priority, mode=mode):
                    recipe = automatic_recipe(priority, mode, settings)
                    self.assertEqual(recipe['iterations'],
                                     1 if mode in ('single_shot', 'regenerate_only') else 5)
                    self.assertEqual((recipe['cost'], recipe['seconds']), (0.07, 410))

    def test_default_budgets_are_shared_by_all_levels_and_modes(self):
        for priority in (15, 35, 55, 75, 90):
            for mode in ('iterative', 'single_shot', 'regenerate_only', 'regenerate_refine'):
                recipe = automatic_recipe(priority, mode)
                self.assertEqual((recipe['cost'], recipe['seconds']), (0.25, 360))

    def test_invalid_resource_limits_are_rejected_not_clamped(self):
        for key, values in {
            'remediation_max_iterations': ('', '0', '11', '1.5', 'bad', True),
            'remediation_max_cost_usd': ('', '0', '.009', '100.01', 'NaN', 'sNaN', 'Infinity', 'bad'),
            'remediation_max_execution_seconds': ('', '29', '7201', '30.5', 'bad'),
        }.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    common_conditions({key: value})

    def test_configured_targets_are_shared_by_all_interventions_and_baseline(self):
        settings = {'remediation_min_lighthouse': '97', 'remediation_max_axe': '0'}
        for priority in (15,35,55,75,90):
            for execution in ('iterative','single_shot'):
                recipe = automatic_recipe(priority, execution, settings=settings)
                self.assertEqual((recipe['lighthouse'], recipe['axe']), (97,0))
        self.assertEqual(COMMON_CONDITIONS['lighthouse'],90)
        self.assertEqual(COMMON_CONDITIONS['axe'],5)

    def test_invalid_targets_are_rejected_not_clamped(self):
        for key, values in {
            'remediation_min_lighthouse': ('', '-1', '101', '94.5', 'bad', True),
            'remediation_max_axe': ('', '-1', '2147483648', '1.2', 'bad'),
        }.items():
            for value in values:
                with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                    common_conditions({key:value})

    def test_intervention_does_not_change_acceptance_or_evidence_budget(self):
        for priority in (15, 35, 55, 75, 90):
            recipe = automatic_recipe(priority)
            for key, value in COMMON_CONDITIONS.items():
                self.assertEqual(recipe[key], value, (priority, key))

    def test_temperature_still_changes_with_intervention(self):
        self.assertEqual(automatic_recipe(15)["temperature"], 0.05)
        self.assertEqual(automatic_recipe(90)["temperature"], 0.50)

    def test_five_steps_keep_the_confirmed_temperature_defaults(self):
        self.assertEqual([automatic_recipe(priority)['temperature']
                          for priority in (15,35,55,75,90)],
                         [0.05,0.20,0.50,0.50,0.50])

    def test_baseline_is_independent_of_hidden_preservation_slider(self):
        for priority in (15,35,55,75,90):
            self.assertEqual(automatic_recipe(priority,'single_shot'),
                             automatic_recipe(15,'single_shot'))
        self.assertEqual(automatic_recipe(55,'single_shot')['iterations'],1)
