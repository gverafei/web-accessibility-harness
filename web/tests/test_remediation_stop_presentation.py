import copy
import unittest

from remediation_stop_presentation import stop_notice


def translate(message, **values):
    return message % values if values else message


class StopPresentationTests(unittest.TestCase):
    def test_frozen_limits_and_receipts_are_not_modified(self):
        run = {'harness_outcome':{'stop_reason':'Request reservation exceeds the per-call cost limit; no HTTP request sent'},
               'total_cost_usd':'0.16424688','max_cost_usd':'1'}
        manifest = {role:{'max_call_cost_usd':.25} for role in ('repair_budget','review_budget')}
        original = copy.deepcopy((run,manifest))
        message = stop_notice(run,translate,manifest)['message']
        self.assertIn('US$0.25',message)
        self.assertIn('US$0.164247 of US$1.00',message)
        self.assertEqual((run,manifest),original)

    def test_missing_or_different_role_limits_do_not_invent_a_ceiling(self):
        run = {'error_message':'Request reservation exceeds the per-call cost limit; no HTTP request sent'}
        for manifest in (None,{'repair_budget':{'max_call_cost_usd':1},'review_budget':{'max_call_cost_usd':.25}}):
            message = stop_notice(run,translate,manifest)['message']
            self.assertIn('per-request limit',message)
            self.assertNotIn('US$',message)

    def test_resource_stops_distinguish_cost_context_count_and_time(self):
        cases = {'Insufficient account budget for a bounded request':'remaining authorized budget',
                 'Campaign cost limit reached':'remaining authorized budget',
                 'Shared total cost limit reached':'remaining authorized budget',
                 'Shared stage cost limit reached':'remaining authorized budget',
                 'Provider call limit reached':'request count limit',
                 'Provider account time limit reached':'execution time limit',
                 'Request exceeds the declared model context bound; no truncation was performed':'model context limit'}
        for reason,expected in cases.items():
            with self.subTest(reason=reason):
                self.assertIn(expected,stop_notice({'error_message':reason},translate)['message'])
        for reason in ('402 Payment required','ConnectionError: network unavailable',''):
            self.assertIsNone(stop_notice({'error_message':reason},translate))
