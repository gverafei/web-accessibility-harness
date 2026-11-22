"""Coordinate declared native list role repairs without broadening patch scope."""
import unittest
from copy import deepcopy
from unittest.mock import patch
from bs4 import BeautifulSoup
from coordinated_role_validation import VERSION
from remediation_approaches import constrain_plan
from remediation_interventions import VERSION as INTERVENTION, approach, coordinated_plan
from harness.html_tools import apply_repair_plan
from harness.controller import materialize
import json

SOURCE = '<ul id="nav" role="menu"><li id="item" role="menuitem"><a href="/go">Go</a></li></ul><button id="other">More</button>'


def plan():
    return {
        'operations': [
            {'action': 'remove_attribute', 'selector': '#nav', 'name': 'role'},
            {'action': 'remove_attribute', 'selector': '#item', 'name': 'role'}],
        'root_causes': [{'id': 'navigation', 'selectors': ['#nav', '#item'],
                         'depends_on': [], 'operation_indexes': [0, 1]}]}


class CoordinatedRoleTests(unittest.TestCase):
    def bound(self, source, proposal, version=VERSION):
        ordered, _ = coordinated_plan(source, proposal)
        return constrain_plan(source, ordered, approach(3, INTERVENTION),
                              validation_version=version)

    def test_final_group_repairs_list_children_in_either_operation_order(self):
        for reverse in (False, True):
            proposal = plan()
            if reverse:
                proposal['operations'].reverse()
            bounded, rejected = self.bound(SOURCE, proposal)
            self.assertEqual(rejected, [])
            candidate, result = apply_repair_plan(SOURCE, bounded)
            soup = BeautifulSoup(candidate, 'html.parser')
            self.assertIsNone(soup.ul.get('role'))
            self.assertIsNone(soup.li.get('role'))
            self.assertEqual(soup.a['href'], '/go')
            self.assertEqual(soup.get_text(' ', strip=True), 'Go More')
            self.assertEqual(len(result['applied']), 2)

    def test_legacy_guard_keeps_exact_rejections(self):
        bounded, rejected = self.bound(SOURCE, plan(), None)
        self.assertEqual(bounded['operations'], [])
        self.assertEqual(len(rejected), 2)
        self.assertIn('invalid native list children', rejected[0]['reason'])

    def test_uncorrected_and_non_li_children_still_block_the_group(self):
        for source in (SOURCE.replace('role="menuitem"', 'role="button"'),
                       SOURCE.replace('<li', '<div').replace('</li>', '</div>')):
            proposal = plan()
            proposal['operations'] = proposal['operations'][:1]
            proposal['root_causes'][0]['operation_indexes'] = [0]
            bounded, rejected = self.bound(source, proposal)
            self.assertFalse(bounded['operations'])
            self.assertEqual(len(rejected), 1)

    def test_independent_group_cannot_satisfy_a_prerequisite(self):
        proposal = plan()
        proposal['root_causes'] = [
            {'id': 'parent', 'selectors': ['#nav'], 'operation_indexes': [0], 'depends_on': []},
            {'id': 'child', 'selectors': ['#item'], 'operation_indexes': [1], 'depends_on': []}]
        bounded, rejected = self.bound(SOURCE, proposal)
        self.assertEqual([op['selector'] for op in bounded['operations']], ['#item'])
        self.assertEqual(len(rejected), 1)

    def test_explicit_child_prerequisite_is_checked_before_parent(self):
        proposal = plan()
        proposal['root_causes'] = [
            {'id': 'parent', 'selectors': ['#nav'], 'operation_indexes': [0], 'depends_on': ['child']},
            {'id': 'child', 'selectors': ['#item'], 'operation_indexes': [1], 'depends_on': []}]
        bounded, rejected = self.bound(SOURCE, proposal)
        self.assertFalse(rejected)
        self.assertEqual([op['selector'] for op in bounded['operations']], ['#item', '#nav'])

    def test_protected_task_and_hidden_semantics_still_block_the_whole_cause(self):
        for extra in (
                {'action': 'set_attribute', 'selector': '#item a', 'name': 'href', 'value': '/else'},
                {'action': 'set_attribute', 'selector': '#item', 'name': 'aria-hidden', 'value': 'true'},
                {'action': 'set_attribute', 'selector': '#item', 'name': 'role', 'value': 'none'}):
            proposal = plan()
            proposal['operations'].append(extra)
            proposal['root_causes'][0]['operation_indexes'].append(2)
            proposal['root_causes'][0]['selectors'].append(extra['selector'])
            bounded, rejected = self.bound(SOURCE, proposal)
            self.assertFalse(bounded['operations'])
            self.assertEqual(len(rejected), 3)

    def test_failed_cause_blocks_dependents_but_keeps_independent_work(self):
        proposal = plan()
        proposal['operations'] = [proposal['operations'][0],
            {'action': 'set_attribute', 'selector': '#item', 'name': 'aria-label', 'value': 'Go'},
            {'action': 'set_attribute', 'selector': '#other', 'name': 'aria-label', 'value': 'More choices'}]
        proposal['root_causes'] = [
            {'id': 'parent', 'selectors': ['#nav'], 'operation_indexes': [0], 'depends_on': []},
            {'id': 'dependent', 'selectors': ['#item'], 'operation_indexes': [1], 'depends_on': ['parent']},
            {'id': 'other', 'selectors': ['#other'], 'operation_indexes': [2], 'depends_on': []}]
        bounded, rejected = self.bound(SOURCE, proposal)
        self.assertEqual([op['selector'] for op in bounded['operations']], ['#other'])
        self.assertEqual(len(rejected), 2)

    def test_native_p2_and_shared_executor_materialize_the_same_patch(self):
        bounded, _ = self.bound(SOURCE, plan())
        expected, _ = apply_repair_plan(SOURCE, bounded)
        candidate, evidence = materialize(SOURCE, json.dumps(plan()), 3,
            'https://example.test', intervention_version=INTERVENTION,
            validation_version=VERSION)
        self.assertEqual(candidate, expected)
        self.assertFalse(evidence['rejected'])

    def test_manifest_freezes_new_contract_without_rewriting_old_manifests(self):
        from harness.contracts import validate_manifest, ContractError
        from test_slider_bridge import BridgeTests
        fixture = BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        old = deepcopy(fixture.manifest)
        self.assertNotIn('patch_validation_version', validate_manifest(old))
        new = deepcopy(old)
        new['patch_validation_version'] = VERSION
        self.assertEqual(validate_manifest(new)['patch_validation_version'], VERSION)
        new['patch_validation_version'] = 'unknown'
        with self.assertRaises(ContractError):
            validate_manifest(new)

    def test_fixed_and_dynamic_registration_freeze_the_same_validator(self):
        from harness.remediation_bridge import configure
        from harness.decision_models import DEFINITIONS
        from test_slider_bridge import BridgeTests
        fixture = BridgeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        group = {'id': 'fixture-budget', 'total_usd': 30,
                 'stage_limits': {'remediation': 30}}
        controls = {'corpora': [{'id': fixture.corpus['id']}], 'groups': [group]}
        values = {'harness_corpus': fixture.corpus['id'],
                  'harness_budget_group': group['id'], 'harness_verifier': 'cheap',
                  'max_cost_usd': '5', 'harness_max_call_cost_usd': '5',
                  'max_execution_seconds': '900', 'max_iterations': '5',
                  'max_axe': '0', 'min_lighthouse': '100'}
        with patch('remediation_model_choices.model_choices', return_value=fixture.workers), \
             patch('harness.remediation_bridge.options', return_value=controls), \
             patch('harness.decision_models.capture_choices', return_value=fixture.workers), \
             patch('harness.decision_models.catalogue', return_value=DEFINITIONS):
            for public_level in (2, 5):
                config = configure(fixture.store, {},
                    {'id': 7, 'url': 'https://fixture.example/'}, fixture.workers[0],
                    {**values, 'preservation_level': str(public_level - 1)})
                manifest = fixture.store.get(config['campaign_id'])['data']
                self.assertEqual(manifest['patch_validation_version'], VERSION)

    def test_unknown_contract_fails_closed(self):
        with self.assertRaises(ValueError):
            self.bound(SOURCE, plan(), 'unknown')


if __name__ == '__main__':
    unittest.main()
