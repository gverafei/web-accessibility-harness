"""Regenerated controls can repair target size without granting global layout edits."""
import unittest
from remediation_interventions import VERSION,PRESERVATION_VERSION,approach
from remediation_approaches import constrain_plan,refinement_approach
from remediation_patch_prompt import scope_instruction
from harness.html_tools import apply_repair_plan,content_retention


class RegenerationTargetSizeTests(unittest.TestCase):
    source='<!doctype html><html><head><style>.eyebrow{display:block;font-size:11px;line-height:1.4}</style></head><body><main id="main"><a id="topic" class="eyebrow" href="/politics">Politics</a><h2><a href="/article">Article</a></h2></main></body></html>'

    def test_local_native_control_size_repair_is_advertised_and_executable(self):
        for wire in (4,5):
            policy=refinement_approach(approach(wire,VERSION),True)
            self.assertEqual(policy.step,2)
            self.assertEqual(policy.max_operations,35)
            self.assertIn('min-width/min-height',scope_instruction(policy))
            accepted,rejected=constrain_plan(self.source,{'operations':[{'action':'append_css','selector':'#topic','css':'min-height:24px;'}]},policy)
            self.assertFalse(rejected)
            document,result=apply_repair_plan(self.source,accepted)
            self.assertTrue(result['applied'])
            retention=content_retention(self.source,document,'https://example.test/')
            self.assertEqual([retention[k]for k in ['text_percent','links_percent','images_percent']],[100,100,100])

    def test_runtime_prompt_and_executor_share_the_local_refinement_contract(self):
        import ast
        from pathlib import Path
        tree=ast.parse((Path(__file__).resolve().parents[1]/'app/remediation_jobs.py').read_text())
        assignments=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='execution_approach'for t in n.targets)]
        self.assertEqual(len(assignments),1)
        self.assertEqual(assignments[0].value.func.id,'refinement_approach')
        guards=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='constrain_plan']
        self.assertEqual(guards[0].args[2].id,'execution_approach')
        original=approach(1,VERSION)
        self.assertIs(refinement_approach(original,False),original)
        self.assertEqual(refinement_approach(approach(5,PRESERVATION_VERSION),True).version,'five-fixed-levels-v8')

    def test_existing_minimal_and_historical_contracts_are_not_widened(self):
        for policy in [approach(1,VERSION),approach(4,PRESERVATION_VERSION),approach(5,PRESERVATION_VERSION)]:
            self.assertTrue(constrain_plan(self.source,{'operations':[{'action':'append_css','selector':'#topic','css':'min-height:24px;'}]},policy)[1])

    def test_regions_large_sizes_and_arbitrary_spacing_remain_forbidden(self):
        for wire in (4,5):
            for selector,css in [('#main','min-height:24px;'),('#topic','min-height:100vh;'),('#topic','min-width:45px;'),('#topic','margin-bottom:20px;'),('#topic','display:none;')]:
                with self.subTest(wire=wire,css=css):
                    self.assertTrue(constrain_plan(self.source,{'operations':[{'action':'append_css','selector':selector,'css':css}]},approach(wire,VERSION))[1])


if __name__=='__main__':unittest.main()
