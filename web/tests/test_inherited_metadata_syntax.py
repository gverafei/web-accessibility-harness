import copy
import unittest
from harness.syntax_policy import localize,compare


class InheritedMetadataSyntaxTests(unittest.TestCase):
    def evidence(self,document,selectors):
        raw={'state':'violated','validator':'html-validate','version':'fixture',
             'errors':[{'rule':'element-permitted-content','message':'META under BODY','selector':s,
                        'context':{'child':'<meta>','kind':'content','parent':'<body>'}}for s in selectors]}
        return raw,localize(raw,document,'https://example.org/')

    def test_identical_acquired_metadata_is_inherited_after_sibling_selector_changes(self):
        source='<body id="page"><p>Original</p><meta name="csrf" data-token="fixture"><p>Footer</p><meta name="telemetry" data-env="fixture"></body>'
        candidate='<body id="page"><meta data-token="fixture" name="csrf"><p>Original</p><p>Footer</p></body>'
        raw,before=self.evidence(source,['#page > meta:nth-child(2)','#page > meta:nth-child(4)'])
        snapshot=copy.deepcopy(raw);_,after=self.evidence(candidate,['#page > meta'])
        result=compare(after,before)
        self.assertEqual(result['state'],'passed');self.assertEqual(len(result['inherited']),1)
        self.assertEqual(raw,snapshot)

    def test_changed_or_extra_metadata_remains_introduced(self):
        source='<body><meta name="csrf" data-token="fixture"></body>';_,before=self.evidence(source,['body > meta'])
        _,changed=self.evidence(source.replace('fixture','changed'),['body > meta'])
        self.assertEqual(compare(changed,before)['state'],'violated')
        _,duplicate=self.evidence(source.replace('</body>','<meta name="csrf" data-token="fixture"></body>'),['body > meta:nth-child(1)','body > meta:nth-child(2)'])
        result=compare(duplicate,before);self.assertEqual(len(result['inherited']),1);self.assertEqual(len(result['introduced']),1)

    def test_a_valid_head_metadata_element_cannot_waive_a_new_body_violation(self):
        source='<head><meta name="csrf" data-token="fixture"></head><body><p>Original</p></body>'
        baseline=localize({'state':'passed','validator':'html-validate','version':'fixture','errors':[]},source,'https://example.org/')
        _,after=self.evidence('<body><meta name="csrf" data-token="fixture"></body>',['body > meta'])
        self.assertEqual(compare(after,baseline)['state'],'violated')
