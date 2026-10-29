import unittest
from remediation_interventions import VERSION, LEGACY_VERSION, POLICIES, WIRES, active_wires, approach, coordinated_plan, public_to_wire, wire_to_public


class FourPolicyTests(unittest.TestCase):
    def test_four_public_policies_and_dynamic_do_not_renumber_old_wire_ids(self):
        self.assertEqual([p.level for p in POLICIES],[1,2,3,4])
        self.assertEqual(WIRES,(1,3,4,5))
        self.assertEqual([public_to_wire(i)for i in range(1,6)],[1,3,4,5,6])
        self.assertEqual([wire_to_public(i)for i in(1,3,4,5,6)],[1,2,3,4,5])
        self.assertEqual(approach(3,VERSION).engine,'structural_patch')
        self.assertEqual(approach(3,LEGACY_VERSION).name,'Coordinated repair')
        with self.assertRaises(ValueError):approach(2,VERSION)
        with self.assertRaises(ValueError):public_to_wire(True)
        with self.assertRaises(ValueError):public_to_wire(6)

    def test_dynamic_current_pool_excludes_retired_localized_arm(self):
        self.assertEqual(active_wires({'intervention_version':VERSION}),(1,3,4,5))
        self.assertEqual(active_wires({}),(1,2,3,4,5))
        with self.assertRaises(ValueError):active_wires({'intervention_version':'invented'})

    def test_empty_plan_does_not_force_a_fabricated_root_cause(self):
        plan,evidence=coordinated_plan('<button id="go">Go</button>',{'operations':[]})
        self.assertEqual(plan['operations'],[])
        self.assertEqual(evidence['operation_order'],[])

    def test_verified_dependencies_order_the_actual_operations(self):
        source='<p id="help">Help</p><input id="field">'
        plan={'operations':[{'action':'set_attribute','selector':'#field','name':'aria-describedby','value':'help'},
                            {'action':'set_attribute','selector':'#help','name':'role','value':'note'}],
              'root_causes':[{'id':'field','selectors':['#field'],'depends_on':['help'],'operation_indexes':[0]},
                             {'id':'help','selectors':['#help'],'depends_on':[],'operation_indexes':[1]}]}
        ordered,evidence=coordinated_plan(source,plan)
        self.assertEqual(evidence['operation_order'],[1,0])
        self.assertEqual([op['selector']for op in ordered['operations']],['#help','#field'])

    def test_cycles_unknown_selectors_and_duplicated_assignments_are_rejected(self):
        source='<p id="help">Help</p>'
        operation={'action':'set_attribute','selector':'#help','name':'role','value':'note'}
        valid={'id':'a','selectors':['#help'],'depends_on':[],'operation_indexes':[0]}
        for groups in ([dict(valid,depends_on=['a'])], [dict(valid,depends_on=['missing'])],
                       [dict(valid,selectors=['#missing'])], [dict(valid,operation_indexes=[0,0])]):
            with self.subTest(groups=groups),self.assertRaises(ValueError):
                coordinated_plan(source,{'operations':[operation],'root_causes':groups})
