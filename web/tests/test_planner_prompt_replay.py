import unittest
from remediation_call_evidence import equivalent_patch_prompt

PREFIX='You are the information-architecture/accessibility planning specialist, not the generator. Source <main>fixed</main>\nFailures: '

class PlannerPromptReplayTests(unittest.TestCase):
    def test_only_dictionary_key_order_in_failure_evidence_is_equivalent(self):
        a=PREFIX+'[{"rule":"name","help":"Name","nodes":[{"target":"#x","text":"Keep"}]}]\nContract: exact'
        b=PREFIX+'[{"help":"Name","nodes":[{"text":"Keep","target":"#x"}],"rule":"name"}]\nContract: exact'
        self.assertTrue(equivalent_patch_prompt(a,b))
        for changed in (b.replace('Keep','Changed'),b.replace('fixed','other'),
                        b.replace('Contract: exact','Contract: changed'),b.replace('"name"','true')):
            self.assertFalse(equivalent_patch_prompt(a,changed))

    def test_array_order_and_embedded_strings_remain_exact(self):
        a=PREFIX+'[{"x":1},{"x":2}]'
        self.assertFalse(equivalent_patch_prompt(a,PREFIX+'[{"x":2},{"x":1}]'))
        self.assertFalse(equivalent_patch_prompt(PREFIX+'[{"text":"{a:1,b:2}"}]',
                                               PREFIX+'[{"text":"{b:2,a:1}"}]'))
        self.assertFalse(equivalent_patch_prompt(a,a+'\nFailures: []'))

    def test_other_prompt_families_cannot_use_this_equivalence(self):
        a='Unrelated prompt\nFailures: [{"a":1,"b":2}]'
        b='Unrelated prompt\nFailures: [{"b":2,"a":1}]'
        self.assertFalse(equivalent_patch_prompt(a,b))
