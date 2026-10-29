import tempfile,unittest
from unittest.mock import Mock
from harness.destination_repairs import cases
from harness.refinement_decisions import choose
from harness.store import Store
from remediation_approaches import constrain_plan,APPROACHES
from remediation_jobs import apply_repair_plan

class DestinationRefinementTests(unittest.TestCase):
    def test_exact_source_correction_is_executable_only_with_witness_and_opt_in(self):
        source='<a href="/jobs/research-jobs-town">Research</a>'
        candidate='<main><h1>Jobs</h1><a href="/jobs/research-town">Research</a></main>'
        invalid=[{'element':'a','attribute':'href','target':'https://example.test/jobs/research-town'}]
        repairs=cases(source,candidate,'https://example.test/',invalid);self.assertEqual(len(repairs),1)
        operation={'action':'set_attribute','selector':repairs[0]['selector'],'name':'href','value':repairs[0]['after']}
        self.assertTrue(constrain_plan(candidate,{'operations':[operation]},APPROACHES[1])[1])
        self.assertTrue(constrain_plan(candidate,{'operations':[operation]},APPROACHES[0],destination_repairs=repairs)[1])
        plan,rejected=constrain_plan(candidate,{'operations':[operation]},APPROACHES[1],destination_repairs=repairs)
        self.assertFalse(rejected);result,_=apply_repair_plan(candidate,plan)
        self.assertIn('https://example.test/jobs/research-jobs-town',result);self.assertIn('<h1>Jobs</h1>',result)
        operation['value']='https://attacker.test/'
        self.assertTrue(constrain_plan(candidate,{'operations':[operation]},APPROACHES[1],destination_repairs=repairs)[1])

    def test_ambiguous_labels_unknown_labels_and_mixed_selector_matches_do_not_grant_permission(self):
        invalid=[{'element':'a','attribute':'href','target':'https://example.test/bad'}]
        for reference,candidate in [('<a href="/a">Go</a><a href="/b">Go</a>','<a href="/bad">Go</a>'),
                                    ('<a href="/a">Go</a>','<a href="/bad">Other</a>'),
                                    ('<a href="/a">Go</a>','<a href="/bad">Go</a><a href="/bad">Other</a>')]:
            self.assertEqual(cases(reference,candidate,'https://example.test/',invalid),[])

    def test_decisions_reviews_the_specific_repair_and_reuses_its_record(self):
        with tempfile.TemporaryDirectory()as root:
            store=Store(root);providers=Mock(campaign='fixture');providers.decisions.return_value={'action':{'type':'choice','choice':'repair_known_destinations'}}
            evidence={'candidate':{'axe':0,'lighthouse':100},'destination_repairs':[{'before':'/bad','after':'/real'}]}
            first=choose(store,providers,'run','refinement',{'model':'fixture-decisions'},evidence)
            second=choose(store,providers,'run','refinement',{'model':'fixture-decisions'},evidence)
            self.assertEqual(first,second);providers.decisions.assert_called_once()
            self.assertEqual(first['data']['action'],'repair_known_destinations')
            self.assertIn('not a reason to stop',providers.decisions.call_args.args[4][0]['instructions'])
