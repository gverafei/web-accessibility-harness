import json
import unittest
import remediation_patch_context as module

class NestedTargets(unittest.TestCase):
    def test_nested_browser_path_remains_distinct_from_local_selector(self):
        html='<html><head><title>Page</title></head><body><main><button id="real">Go</button><div id="host"></div></main></body></html>'
        nested=[['#host','#shadow-button']]
        axe=[{'nodes':[{'target':nested},{'target':['#real']},{'target':nested},{'target':['iframe','#button']}]}]
        result=json.loads(module.repair_context(html,axe,[{'items':[{'selector':['#host','#inner']}]}]))
        self.assertEqual([x['selector']for x in result['selector_evidence']],['#real'])
        self.assertEqual(result['affected_nodes'][0]['attributes']['id'],'real')
        self.assertEqual(len(result['unresolved_targets']),3)
        self.assertEqual(result['unresolved_targets'][0]['target'],nested)
    def test_large_nested_context_remains_bounded(self):
        source='<html><head><title>Page</title></head><body><main>Content</main></body></html>'
        result=module.repair_context(source,[{'nodes':[{'target':[['#'+('a'*12000)]]}]}],[],limit=4000)
        self.assertLessEqual(len(result),4000)
        self.assertEqual(json.loads(result)['unresolved_targets_omitted'],1)

if __name__=='__main__':unittest.main()
