import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from jinja2 import Environment, FileSystemLoader

APP = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP))
from remediation_rag import retrieval_query, prompt_context, AXE_ACT_TERMS, adaptive_example_limit
from remediation_rag_supplement import PAIRS, points


class SupplementTests(unittest.TestCase):
    def test_adaptive_limit_covers_three_concepts_and_is_bounded(self):
        self.assertEqual(adaptive_example_limit([{'rule': r} for r in ('label','region','target-size')]), 6)
        self.assertEqual(adaptive_example_limit([{'rule': r} for r in ('label','region','target-size','page-has-heading-one','listitem')]), 10)
        self.assertEqual(adaptive_example_limit([{'rule': r} for r in AXE_ACT_TERMS]), 12)
        self.assertEqual(adaptive_example_limit([{'rule': 'region'}]), 4)
        self.assertEqual(adaptive_example_limit([{'rule': 'unknown'}]), 4)

    @patch('remediation_rag.requests.post')
    def test_plateau_rotates_relevant_pairs_without_exceeding_budget(self, post):
        response = Mock()
        response.json.return_value = {'result': {'points': [
            {'payload': p['payload']} for p in points()
            if p['payload']['axe_rule'] in ('target-size', 'region')]}}
        post.return_value = response
        from remediation_rag import retrieve
        query = retrieval_query([{'rule': 'target-size', 'impact': 'serious'},
            {'rule': 'region', 'impact': 'moderate'}])
        result = retrieve(query, 2, previously_supplied={'platform-axe-target-size'})
        self.assertEqual(len(result), 2)
        self.assertEqual({p['axe_rule'] for p in result}, {'region'})
        self.assertEqual({p['expected'] for p in result}, {'passed', 'failed'})

    @patch('remediation_rag.requests.post')
    def test_measured_priority_beats_longer_lexical_concept(self, post):
        response = Mock()
        response.json.return_value = {'result': {'points': [
            {'payload': p['payload']} for p in points()
            if p['payload']['axe_rule'] in ('target-size', 'region')]}}
        post.return_value = response
        from remediation_rag import retrieve
        query = retrieval_query([{'rule': 'target-size', 'impact': 'minor'},
            {'rule': 'region', 'impact': 'moderate'}])
        result = retrieve(query, 2)
        self.assertEqual({p['axe_rule'] for p in result}, {'region'})

    def test_pairs_are_complete_stable_and_correctly_attributed(self):
        batch = points()
        self.assertEqual(len(batch), 2 * len(PAIRS))
        self.assertEqual([p['id'] for p in batch], [p['id'] for p in points()])
        for rule in PAIRS:
            pair = [p['payload'] for p in batch if p['payload']['axe_rule'] == rule]
            self.assertEqual({p['expected'] for p in pair}, {'passed', 'failed'})
            self.assertEqual({p['rule_name'] for p in pair}, {AXE_ACT_TERMS[rule]})
            for p in pair:
                self.assertTrue(p['code'].endswith('</html>'))
                self.assertIn('not official ACT', prompt_context([p]))
                self.assertIn(p['guidance'], prompt_context([p]))
                self.assertIn(p['rule_name'], retrieval_query([{'rule': rule}]))

    def test_iteration_rag_indicator_stays_visible_and_examples_are_disclosed(self):
        env = Environment(loader=FileSystemLoader(APP / 'templates'), autoescape=True)
        env.globals['_'] = lambda text: text
        template = env.get_template('_remediation_iteration_rag.html')
        used = template.render(item={'strategy': {'rag': {'enabled': True, 'retrieved': [points()[0]['payload']]}}})
        self.assertIn('RAG-ACT used', used)
        self.assertIn('not an official ACT testcase', used)
        summary = used.split('<summary>', 1)[1].split('</summary>', 1)[0]
        self.assertIn('RAG-ACT used · 1 examples', summary)
        self.assertNotIn('ACT examples guide repairs', summary)
        self.assertNotIn(' open', used.split('>', 1)[0])
        self.assertIn('</details>', used)
        empty = template.render(item={'strategy': {'rag': {'enabled': True, 'retrieved': []}}})
        self.assertIn('The reason was not recorded.', empty)
        self.assertNotIn('RAG-ACT used', empty)

    def test_nonuse_requires_recorded_reason(self):
        from remediation_report_presentation import rag_explanation
        rag={'enabled':True,'retrieved':[]}
        self.assertIn('not recorded',rag_explanation(rag))
        self.assertIn('no examples matching',rag_explanation(rag,{'method':'mapped','mapped_index_candidates':[]}))
        self.assertIn('complete passing/failing',rag_explanation(rag,{'abstention':'no complete admissible evidence pair'}))
        self.assertIn('retrieval failed',rag_explanation(rag,{'error':'unavailable'}))
        self.assertIn('disabled',rag_explanation({'enabled':False}))
        self.assertIn('No measured',rag_explanation(rag,{'abstention':'no measured defects'}))

    def test_decisions_log_normalizes_actual_wire_questions(self):
        from remediation_report_presentation import recorded_questions, event_presentation
        self.assertEqual(recorded_questions({'q':{'instructions':'Judge this control','criteria':{'failed':'Bad','passed':'Good'}}}), [{'name':'q','instructions':'Judge this control','choices':['failed','passed']}])
        event={'event_type':'decisions_call','decision_role':'Complementary taxonomy evaluation'}
        event_presentation(event)
        self.assertIn('batch of elements',event['activity_description'])

    def test_progress_translation_preserves_recorded_runtime_message(self):
        from remediation_report_presentation import progress_presentation
        original='Evaluating candidate 2 with Axe and Lighthouse'
        translated=progress_presentation(original,lambda text,**values:('Evaluando %(number)s con %(tools)s'%values)if values else text)
        self.assertEqual(translated,'Evaluando 2 con Axe and Lighthouse')
        self.assertEqual(original,'Evaluating candidate 2 with Axe and Lighthouse')
        self.assertEqual(progress_presentation('Unrecognized recorded event'),'Unrecognized recorded event')
