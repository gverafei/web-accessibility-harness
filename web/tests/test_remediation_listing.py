import unittest
import tempfile
from harness.store import Store
from remediation_listing import hydrate_search
from remediation_continuation_presentation import continuation_note


def translate(message, **values):
    return message % values if values else message


class RecordedContinuationPresentation(unittest.TestCase):
    def test_search_uses_real_iteration_ids_and_saved_labels_without_changing_records(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            for run_id in (380,432,999):
                store.append('verification_case', {'run_id':run_id,'key':'B-0037','secret':'not indexed'})
            store.append('verification_response', {'run_id':380,'key':'not a case label'})
            before = [(r['id'],r['hash'])for r in store.list()]
            rows = [{'id':380},{'id':432}]
            hydrate_search(rows,[{'run_id':380,'id':2110,'iteration_number':1},
                                 {'run_id':380,'id':2112,'iteration_number':3},
                                 {'run_id':999,'id':2999,'iteration_number':5}],store)
            self.assertEqual(rows[0]['search_ids'],{'run':'380','iterations':['2110','2112']})
            self.assertEqual(rows[1]['search_ids'],{'run':'432','iterations':[]})
            self.assertEqual([r['search_aliases']for r in rows],[['B-0037'],['B-0037']])
            self.assertNotIn('secret',repr(rows))
            self.assertEqual([(r['id'],r['hash'])for r in store.list()],before)

    def test_continue_names_recorded_defects_without_inventing_a_diagnosis(self):
        item = {'continuation_review': {'action': 'continue', 'findings': {
            'candidate': {'axe': 0, 'lighthouse': 100},
            'functional_evidence': {'broken_image_urls': ['one', 'two']},
            'remaining_taxonomy_failures': {'Semantic': 3}, 'visual_impact': 'material'}}}
        note = continuation_note(item, {'status': 'accepted'}, True, translate)
        self.assertEqual(note['label'], 'Next iteration')
        self.assertIn('Images not loading: 2', note['findings'])
        self.assertIn('Semantic findings: 3', note['findings'])
        self.assertNotIn('Axe findings: 0', note['findings'])
        note = continuation_note({}, {'status': 'accepted'}, True, translate)
        self.assertEqual(note['reason'], 'No detailed continuation reason was recorded.')

    def test_last_iteration_reports_closure_even_if_an_old_advisory_requested_more(self):
        item = {'continuation_review': {'action': 'continue'}}
        run = {'status': 'accepted', 'harness_outcome': {'stop_reason': 'perfect_audit_stop_requested'}}
        note = continuation_note(item, run, False, translate)
        self.assertEqual(note['label'], 'Run stopped')
        self.assertIn('Axe 0 and Lighthouse 100', note['reason'])
        self.assertEqual(note['findings'], [])
