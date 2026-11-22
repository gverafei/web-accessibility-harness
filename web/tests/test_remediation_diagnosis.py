import unittest
from remediation_diagnosis import diagnosis_needed,diagnosis_prompt,grounded_diagnosis
from remediation_approaches import APPROACHES


class PatchDiagnosisTests(unittest.TestCase):
    def test_regeneration_uses_selected_capture_and_keeps_rendered_inventory(self):
        from pathlib import Path
        source=(Path(__file__).parents[1]/'app'/'remediation_jobs.py').read_text()
        block=source.split('            if initial_regeneration:\n',1)[1].split('            if len(prompt)',1)[0]
        self.assertIn('content=source',block)
        self.assertIn('markdown_representation(source,source_base',block)
        self.assertIn('markdown_quality(source,content,source_base)',block)
        self.assertIn('reference_document=source',block)
        self.assertIn('source_inventory=inventory',block)
        self.assertIn('visual_references=initial_visual',block)
        self.assertNotIn('content=rendered_source',block)
        self.assertNotIn("not in REGENERATION_MODES and",source.split('select_captured_patch_source(source,rendered_source',1)[0].rsplit('        if ',1)[-1])

    def test_all_patch_levels_are_diagnosed_but_not_initial_one_shot(self):
        for step in range(1,6): self.assertFalse(diagnosis_needed(False,False))
        self.assertTrue(diagnosis_needed(False,False,stagnant=True))
        self.assertTrue(diagnosis_needed(False,False,ambiguous=True))
        self.assertTrue(diagnosis_needed(False,False,policy='always'))
        self.assertFalse(diagnosis_needed(False,False,stagnant=True,policy='disabled'))
        self.assertFalse(diagnosis_needed(False,True))
        self.assertFalse(diagnosis_needed(True,False))
        self.assertFalse(diagnosis_needed(False,False,local_model=True))
        with self.assertRaises(ValueError): diagnosis_needed(False,False,policy='unknown')

    def test_each_prompt_contains_its_actual_permissions(self):
        for approach in APPROACHES[:3]:
            prompt=diagnosis_prompt('<button>Original</button>',[],[],'',approach)
            self.assertIn(approach.instruction,prompt)
            self.assertIn('NOT acceptance review',prompt)
        prompt=diagnosis_prompt('x'*30000,[],[],'',APPROACHES[1],True)
        self.assertIn('"context_abbreviated": true',prompt)
        self.assertIn('regenerated page',prompt)

    def test_unsupported_or_stale_recommendations_are_excluded(self):
        def finding(selector,evidence='Original',specialty='semantics'):
            return dict(specialty=specialty,selector=selector,evidence=evidence,recommendation='Use meaningful button name',rule='')
        proposal={'summary':'Focused diagnosis','findings':[finding('#go'),finding('#missing'),finding('#go','invented quote'),finding('#go',specialty='unknown')]}
        result=grounded_diagnosis(proposal,'<button id="go">Original</button>',[])
        self.assertEqual(len(result['findings']),1)
        self.assertEqual(len(result['rejected']),3)
        self.assertFalse(result['acceptance_gate'])

    def test_measured_rule_requires_matching_selector(self):
        proposal={'findings':[dict(specialty='visual',selector='#go',rule='color-contrast',evidence='Measured low contrast',recommendation='Change local foreground')]}
        source='<button id="go">Original</button>'
        self.assertEqual(len(grounded_diagnosis(proposal,source,[{'rule':'color-contrast','nodes':[{'target':['#go']}]}])['findings']),1)
        self.assertEqual(len(grounded_diagnosis(proposal,source,[{'rule':'color-contrast','nodes':[{'target':['#other']}]}])['findings']),0)
        with self.assertRaises(ValueError): grounded_diagnosis({'findings':'wrong'},source,[])


    def test_regeneration_refinement_compares_candidate_and_source_captures(self):
        from pathlib import Path
        import remediation_jobs
        source=Path(remediation_jobs.__file__).read_text()
        self.assertIn("candidate_path=branch_capture(bridge.store,bridge.state['branch'],base_document)",source)
        self.assertIn('candidate_capture=screenshot_message(candidate_path)',source)
        self.assertIn('source_capture=screenshot_message(run.get("source_screenshot_path"))',source)
        self.assertIn('the first attached capture is the best regenerated page',source)
        self.assertIn('The second, when present, is the immutable original capture',source)

class AdvisoryCompletionTest(unittest.TestCase):
    def test_truncated_advice_preserves_paid_usage_and_allows_generation(self):
        from remediation_diagnosis import advisory_diagnosis_call
        from harness.contracts import ModelOutputIncomplete
        usage = (13949, 1200, .00234355, 3.0, 'openai/gpt-6-luna')
        def truncated():
            raise ModelOutputIncomplete('length', usage)
        self.assertEqual(advisory_diagnosis_call(truncated), (None, *usage))

    def test_refusal_and_transport_failures_are_not_treated_as_advice(self):
        from remediation_diagnosis import advisory_diagnosis_call
        from harness.contracts import ModelOutputIncomplete
        for error in (ModelOutputIncomplete('refused',(0,0,0,0,'model')), ConnectionError('offline')):
            def failed():
                raise error
            with self.assertRaises(type(error)):
                advisory_diagnosis_call(failed)
