import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from remediation_rag import VECTOR_SIZE, embed, prompt_context, retrieval_query, retrieve


class RemediationRagTests(unittest.TestCase):
    def test_lighthouse_query_uses_only_known_rule_correspondences(self):
        query=retrieval_query([],lighthouse_evidence=[{'audit':'image-alt','title':'Image alternatives'},
                                                   {'audit':'unrecognized-audit','title':'Unknown'}])
        self.assertIn('AXE_RULES=image-alt ',query)
        self.assertIn('LIGHTHOUSE=',query)
        self.assertNotIn('AXE_RULES=unrecognized-audit',query)

    def test_local_embedding_is_stable_and_normalized(self):
        first = embed('<button aria-label="Save">Save</button>')
        second = embed('<button aria-label="Save">Save</button>')
        self.assertEqual(first, second)
        self.assertEqual(len(first), VECTOR_SIZE)
        self.assertAlmostEqual(sum(value * value for value in first), 1.0, places=5)

    @patch("remediation_rag.requests.post")
    def test_retrieval_preserves_provenance_and_score(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"result":{"points":[{"score":0.88,"payload":{"rule_name":"Button has accessible name","rule_page":"https://www.w3.org/example","expected":"passed","code":"<button>Save</button>"}}]}}
        empty_scroll=Mock(); empty_scroll.raise_for_status.return_value=None; empty_scroll.json.return_value={"result":{"points":[]}}
        post.side_effect = [response,empty_scroll]
        result = retrieve("button accessible name", 4)
        self.assertEqual(result[0]["rule_name"], "Button has accessible name")
        self.assertEqual(result[0]["score"], 0.88)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["limit"], 16)

    @patch("remediation_rag.requests.post")
    def test_retrieval_pairs_passed_and_failed_examples_from_same_rule(self, post):
        response=Mock(); response.raise_for_status.return_value=None
        response.json.return_value={"result":{"points":[
            {"score":.91,"payload":{"rule_id":"button","rule_name":"Button name","expected":"passed"}},
            {"score":.90,"payload":{"rule_id":"image","rule_name":"Image alt","expected":"failed"}},
            {"score":.88,"payload":{"rule_id":"button","rule_name":"Button name","expected":"failed"}},
        ]}}
        empty_scroll=Mock(); empty_scroll.raise_for_status.return_value=None; empty_scroll.json.return_value={"result":{"points":[]}}
        post.side_effect=[response,empty_scroll]
        result=retrieve("button name",2)
        self.assertEqual([(item["rule_id"],item["expected"]) for item in result],[('button','passed'),('button','failed')])

    @patch("remediation_rag.requests.post")
    def test_exact_act_rule_name_beats_vector_neighbor(self,post):
        vector=Mock(); vector.raise_for_status.return_value=None; vector.json.return_value={"result":{"points":[{"score":.9,"payload":{"rule_id":"form","rule_name":"Form field has non-empty accessible name","expected":"passed"}}]}}
        scroll=Mock(); scroll.raise_for_status.return_value=None; scroll.json.return_value={"result":{"points":[
            {"payload":{"rule_id":"form","rule_name":"Form field has non-empty accessible name","expected":"passed"}},
            {"payload":{"rule_id":"image","rule_name":"Image has non-empty accessible name","expected":"passed"}},
            {"payload":{"rule_id":"image","rule_name":"Image has non-empty accessible name","expected":"failed"}},
        ]}}
        post.side_effect=[vector,scroll]
        result=retrieve("image has non-empty accessible name",2)
        self.assertEqual([(item["rule_id"],item["expected"]) for item in result],[('image','passed'),('image','failed')])

    @patch("remediation_rag.requests.post")
    def test_explicit_axe_rules_do_not_get_padded_with_unrelated_examples(self,post):
        vector=Mock(); vector.raise_for_status.return_value=None; vector.json.return_value={"result":{"points":[]}}
        scroll=Mock(); scroll.raise_for_status.return_value=None; scroll.json.return_value={"result":{"points":[
            {"payload":{"rule_id":"contrast","rule_name":"Text has minimum contrast","expected":"passed"}},
            {"payload":{"rule_id":"contrast","rule_name":"Text has minimum contrast","expected":"failed"}},
            {"payload":{"rule_id":"orientation","rule_name":"Orientation of the page is not restricted using CSS transforms","expected":"passed"}},
        ]}}
        post.side_effect=[vector,scroll]
        query=retrieval_query([{"rule":"color-contrast"}],"")
        result=retrieve(query,4)
        self.assertEqual({item["rule_id"] for item in result},{"contrast"})

    def test_prompt_context_labels_examples_as_evidence(self):
        context = prompt_context([{"rule_name":"Image has text alternative","expected":"failed","requirements":["wcag20:1.1.1"],"rule_page":"https://www.w3.org/example","code":"<img src='x'>"}])
        self.assertIn("failed", context)
        self.assertIn("wcag20:1.1.1", context)
        self.assertIn("<img", context)
        self.assertIn("counterexample to avoid",context)

    @patch('remediation_rag.requests.post')
    def test_real_image_rule_mapping_retrieves_complete_pair_across_pages(self,post):
        def response(result):
            value=Mock(); value.json.return_value={'result':result}; return value
        def example(expected):
            return {'payload':{'rule_id':'image','rule_name':'Image has non-empty accessible name','expected':expected}}
        post.side_effect=[response({'points':[]}),response({'points':[example('passed')],'next_page_offset':'next'}),response({'points':[example('failed')]})]
        result=retrieve(retrieval_query([{'rule':'image-alt'}]),4)
        self.assertEqual([item['expected'] for item in result],['passed','failed'])
        self.assertEqual(post.call_args_list[2].kwargs['json']['offset'],'next')

    @patch('remediation_rag.requests.post')
    def test_unknown_measured_rule_abstains_instead_of_injecting_neighbors(self,post):
        post.return_value.json.return_value={'result':{'points':[{'payload':{'rule_id':'button','rule_name':'Button has non-empty accessible name','expected':'passed'}}]}}
        self.assertEqual(retrieve(retrieval_query([{'rule':'unknown-rule'}]),4),[])

    def test_query_bridges_axe_rule_names_to_act_language(self):
        query=retrieval_query([{"rule":"image-alt"},{"rule":"html-has-lang"}],"missing text alternative")
        self.assertIn("image has non-empty accessible name",query.lower())
        self.assertIn("HTML page has lang attribute",query)

    def test_prompt_omits_oversized_rule_pair_instead_of_truncating_html(self):
        items = [dict(rule_id='button', rule_name='Button name', expected='passed', code='<button>Save</button>'),
                 dict(rule_id='button', rule_name='Button name', expected='failed', code='x' * 5001)]
        self.assertEqual(prompt_context(items), 'No retrieved ACT examples were available.')


if __name__ == "__main__":
    unittest.main()
