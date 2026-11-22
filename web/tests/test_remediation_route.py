import unittest
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader
from remediation_interventions import VERSION
from remediation_route_presentation import execution_route


class RemediationRouteTests(unittest.TestCase):
    def run_data(self, **values):
        return {'id': 42, 'intervention_version': VERSION, 'accessibility_priority': 15,
                'execution_mode': 'iterative', 'dynamic_level': False, **values}

    def iterations(self):
        return [{'id': ident, 'iteration_number': number, 'generator_model': 'recorded/model',
                 'strategy': {'intervention_version': VERSION, 'assigned_level': level}}
                for ident, number, level in [(10, 1, 1), (11, 2, 2), (12, 4, 2)]]

    def test_adaptive_route_uses_actual_strategies_and_marks_only_the_retained_candidate(self):
        run = self.run_data(dynamic_level=True, accepted_iteration_id=11)
        route = execution_route(run, self.iterations())
        self.assertEqual(route['policy'], 'P5')
        self.assertEqual([step['policy'] for step in route['steps']], ['P1', 'P2', 'P2'])
        self.assertEqual([step['id'] for step in route['steps'] if step['retained']], [11])

    def test_wire_identifiers_are_not_shown_as_a_different_public_strategy(self):
        decision = {'data': {'run_id': 'sql-run-42', 'iteration': 3, 'selected': 'P3:worker',
                    'action_descriptors': [{'id': 'P3:worker', 'wire_level': 3, 'level': 2}]}}
        route = execution_route(self.run_data(dynamic_level=True), [], [decision])
        self.assertEqual(route['active'], 'P2')

    def test_stop_or_another_runs_choices_do_not_replace_the_active_strategy(self):
        decisions = [{'data': {'run_id': 'sql-run-42', 'iteration': 4, 'selected': 'stop'}},
                     {'data': {'run_id': 'sql-run-99', 'iteration': 8, 'selected': 'P4:worker'}}]
        route = execution_route(self.run_data(dynamic_level=True), self.iterations(), decisions)
        self.assertEqual(route['active'], 'P2')

    def test_fixed_strategies_and_zero_shot_are_also_visible(self):
        for priority, label in [(15, 'P1'), (55, 'P2'), (75, 'P3'), (90, 'P4')]:
            with self.subTest(label=label):
                route = execution_route(self.run_data(accessibility_priority=priority), [])
                self.assertEqual(route['policy'], label)
                self.assertEqual(route['active'], label)
        self.assertEqual(execution_route(self.run_data(execution_mode='single_shot'), self.iterations())['steps'][0]['policy'], 'P0')

    def test_pending_selection_does_not_invent_an_executed_strategy(self):
        route = execution_route(self.run_data(dynamic_level=True), [])
        self.assertEqual(route['steps'], [])
        self.assertIsNone(route['active'])

    def test_display_ordinals_follow_the_existing_iteration_trace(self):
        iterations = self.iterations()
        iterations[-1]['display_iteration_number'] = 3
        route = execution_route(self.run_data(), iterations)
        self.assertEqual(route['steps'][-1]['iteration'], 3)
        self.assertEqual(iterations[-1]['iteration_number'], 4)

    def test_route_links_match_real_iteration_anchors_and_escape_recorded_model_names(self):
        run = self.run_data(dynamic_level=True, accepted_iteration_id=11)
        rows = self.iterations()
        rows[0]['generator_model'] = '<script>untrusted()</script>'
        run['execution_route'] = execution_route(run, rows)
        environment = Environment(loader=FileSystemLoader(Path(__file__).parents[1] / 'app/templates'), autoescape=True)
        html = environment.get_template('_remediation_route.html').render(run=run, _=lambda value: value)
        page = BeautifulSoup(html, 'html.parser')
        self.assertEqual([link['href'] for link in page.select('a')], ['#iteration-10', '#iteration-11', '#iteration-12'])
        self.assertIsNone(page.select_one('script'))
        self.assertEqual(len(page.select('.is-retained')), 1)
