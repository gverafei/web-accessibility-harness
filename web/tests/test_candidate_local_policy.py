import unittest
from harness.candidate_admission import check
from harness.controller import preserved, retain, materialize
from harness.html_tools import content_retention
from harness.technical import assess
from remediation_interventions import VERSION, PRESERVATION_VERSION, approach, four_policy
from remediation_approaches import constrain_plan
from remediation_selection import candidate_rank
from vera_regeneration import generation_messages, generation_evidence


class CandidateLocalPolicyTests(unittest.TestCase):
    source='<!doctype html><html><head><title>Source</title></head><body><main><h1>Shop</h1><p>Original exact words</p><a href="/buy">Buy</a><input name="legacy"></main></body></html>'
    candidate='<!doctype html><html><head><title>Shop</title><style>main{color:#112;background:white}</style></head><body><main id="content"><h1>Shop</h1><p>Useful new design</p><a href="#content">Top</a></main></body></html>'
    visible={'text':'Shop Useful new design Top','visible_images':0,'broken_images':0,'broken_media':0}

    def test_fidelity_loss_and_syntax_remain_reported_without_veto(self):
        fidelity=preserved(self.source,self.candidate,'https://example.test/',structure_first=True)
        self.assertEqual(fidelity['status'],'violated')
        audit={'status':'completed','syntax':{'state':'violated','errors':1}}
        visual={'status':'admitted'}
        old=assess(audit,fidelity,visual)
        new=assess(audit,fidelity,visual,fidelity_required=False,usability=check(self.candidate,self.visible,'https://example.test/'))
        self.assertNotEqual(old['status'],'passed')
        self.assertEqual(new['status'],'passed')
        self.assertEqual(new['checks']['observable_preservation'],fidelity)
        self.assertFalse(new['fidelity_required'])

    def test_missing_or_rejected_candidate_evidence_never_admits(self):
        audit={'status':'completed','syntax':{'state':'passed','errors':0}}
        for visual,usable in [(None,{'status':'admitted'}),({'status':'admitted'},None),({'status':'rejected'},{'status':'admitted'}),({'status':'admitted'},{'status':'rejected'})]:
            self.assertNotEqual(assess(audit,{'status':'passed'},visual,fidelity_required=False,usability=usable)['status'],'passed')

    def test_diagnostic_mode_keeps_a_measured_regression_and_exact_reviews(self):
        visual={'status':'rejected','rationale':'Fixture clipping'}
        usable={'status':'rejected','reasons':['broken_visible_resources']}
        audit={'status':'completed','syntax':{'state':'violated','errors':1}}
        result=assess(audit,{'status':'violated'},visual,fidelity_required=False,usability=usable,review_mode='diagnostic-only')
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['diagnostic_status'],'violated')
        self.assertEqual(result['checks']['capture_verification'],visual)
        self.assertEqual(result['checks']['candidate_usability'],usable)
        self.assertEqual(result['basis'],'measured-candidate-diagnostic-review-v1')
        self.assertEqual(assess({'status':'failed'}, {'status':'passed'},visual,review_mode='diagnostic-only')['status'],'unverified')

    def test_decorative_cleanup_preserves_named_carrier_and_blocks_informative_matches(self):
        from harness.html_tools import apply_repair_plan
        source='<a id="tip" aria-label="Keyboard help" href="javascript:void(0)"><img id="pixel" src="" style="width:1px!important;height:1px!important"></a><img id="hero" src="" alt="Product" width="1" height="1">'
        plan={'operations':[{'action':'remove_decorative_image','selector':'#pixel'}]}
        bounded,rejected=constrain_plan(source,plan,approach(1,VERSION))
        self.assertFalse(rejected)
        result,execution=apply_repair_plan(source,bounded)
        self.assertEqual(len(execution['applied']),1)
        self.assertNotIn('id="pixel"',result)
        self.assertIn('aria-label="Keyboard help"',result)
        self.assertIn('id="hero"',result)
        mixed={'operations':[{'action':'remove_decorative_image','selector':'img'}]}
        self.assertFalse(constrain_plan(source,mixed,approach(1,VERSION))[0]['operations'])
        untouched,execution=apply_repair_plan(source,mixed)
        self.assertFalse(execution['applied'])
        self.assertIn('id="pixel"',untouched)
        for protected in ['<a href="/go"><img src="" width="1" height="1"></a>', '<img src="/photo" alt="" width="1" height="1">','<img src="" alt="" width="200" height="100">','<img src="" alt="" width="1" height="1" role="button">']:
            bounded,_=constrain_plan(protected,{'operations':[{'action':'remove_decorative_image','selector':'img'}]},approach(1,VERSION))
            self.assertFalse(bounded['operations'])

    def test_candidate_own_broken_resource_and_local_targets_block(self):
        self.assertEqual(check(self.candidate,self.visible,'https://example.test/')['status'],'admitted')
        for source,visible in [(self.candidate.replace('#content','#missing'),self.visible),
                               (self.candidate,self.visible|{'broken_images':1}),
                               (self.candidate,self.visible|{'text':''}),
                               ('<main>Page<input form="missing"></main>',self.visible)]:
            self.assertEqual(check(source,visible,'https://example.test/')['status'],'rejected')
        self.assertEqual(check(self.candidate,None,'https://example.test/')['status'],'review_required')

    def test_unreferenced_destinations_are_diagnostics_not_proof_of_failure(self):
        self.assertEqual(check(self.candidate,self.visible,'https://example.test/',self.source)['status'],'admitted')
        bad=self.candidate.replace('href="#content"','href="/invented-buy"')
        row=check(bad,self.visible,'https://example.test/',self.source)
        self.assertEqual(row['status'],'admitted')
        self.assertEqual(row['reasons'],[])
        self.assertIn('destination_provenance_requires_human_confirmation',row['warnings'])
        self.assertEqual(row['metrics']['unverified_destinations'][0]['target'],'/invented-buy')
        verified=self.candidate.replace('href="#content"','href="/buy"')
        self.assertEqual(check(verified,self.visible,'https://example.test/',self.source)['status'],'admitted')

    def test_query_differences_are_reported_without_inventing_a_new_endpoint(self):
        reference='<a href="https://example.test/help?campaign=original">Help</a>'
        candidate='<a href="https://example.test:443/help">Help</a>'
        result=check(candidate,self.visible,'https://example.test/',reference)
        self.assertEqual(result['status'],'admitted')
        self.assertEqual(len(result['metrics']['destination_query_changes']),1)
        self.assertTrue(check(candidate.replace('/help','/invented'),self.visible,'https://example.test/',reference)['metrics']['unverified_destinations'])
        malformed=check('<a href="https://example.test:wrong/help">Bad</a>',self.visible,'https://example.test/',reference)
        self.assertEqual(malformed['status'],'rejected')

    def test_source_document_alternates_are_grounded_but_assets_are_not_navigation(self):
        reference='<link rel="alternate" hreflang="de" href="https://de.example.test/"><link rel="canonical" href="/home"><link rel="stylesheet" href="/theme.css"><link rel="prefetch" href="/future">'
        for target in ['https://de.example.test/','/home']:
            self.assertEqual(check('<a href="'+target+'">Open</a>',self.visible,'https://example.test/',reference)['status'],'admitted')
        for target in ['/theme.css','/future','https://fr.example.test/','https://de.example.test/invented']:
            self.assertTrue(check('<a href="'+target+'">Open</a>',self.visible,'https://example.test/',reference)['metrics']['unverified_destinations'])

    def test_declared_social_page_address_is_grounded_not_an_arbitrary_fact_or_asset_url(self):
        source='<meta property="og:url" content="https://example.test/CreateAccount"><meta property="og:image" content="/photo.jpg"><meta name="description" content="Try /invented">'
        candidate='<main>Signup<form action="https://example.test/CreateAccount"><input name="username"></form></main>'
        result=check(candidate,self.visible,'https://example.test/',source)
        self.assertEqual(result['status'],'admitted')
        for target in ['/photo.jpg','/invented','/CreateAccount/other']:
            self.assertTrue(check(candidate.replace('https://example.test/CreateAccount',target),self.visible,'https://example.test/',source)['metrics']['unverified_destinations'])
        messages=generation_messages('# Signup','https://example.test/',reference_document=source,creative=True)
        self.assertIn('https://example.test/CreateAccount',str(messages))

    def test_image_can_keep_its_source_asset_in_css_without_an_img_element(self):
        source='<img src="/hero.jpg" alt="Hero"><img src="/other.jpg" alt="Other">'
        candidate='<style>.hero{background-image:url(/hero.jpg)}/* url(/other.jpg) */</style><main class="hero">Hero</main><script>"url(/other.jpg)"</script>'
        old=content_retention(source,candidate,'https://example.test/')
        current=content_retention(source,candidate,'https://example.test/',image_asset_equivalence=True)
        self.assertEqual(old['images_percent'],0)
        self.assertEqual(current['images_percent'],50)
        self.assertEqual(current['image_element_percent'],0)
        self.assertEqual(current['css_image_equivalents'],['https://example.test/hero.jpg'])
        self.assertEqual(current['missing_image_examples'],['https://example.test/other.jpg'])
        from remediation_jobs import build_agent_runtime
        runtime=build_agent_runtime(None,{'intervention_version':VERSION,'max_cost_usd':5,'max_execution_seconds':900},{},1,4)
        actual=runtime.tools.invoke('measure_content_retention',original=source,candidate=candidate,base_url='https://example.test/')
        self.assertEqual(actual['images_percent'],50)
        self.assertEqual(actual['css_image_equivalents'],['https://example.test/hero.jpg'])

    def test_rejected_cause_blocks_its_dependencies_but_keeps_unrelated_repairs(self):
        source='<p id="bad">Bad</p><button id="good">Good</button><p id="dependent">Help</p>'
        plan={'operations':[{'action':'append_css','selector':'#bad','css':'display:none;'},
                            {'action':'set_attribute','selector':'#good','name':'aria-label','value':'Good action'},
                            {'action':'set_attribute','selector':'#dependent','name':'role','value':'note'}],
              'root_causes':[{'id':'bad','selectors':['#bad'],'depends_on':[],'operation_indexes':[0]},
                             {'id':'good','selectors':['#good'],'depends_on':[],'operation_indexes':[1]},
                             {'id':'dependent','selectors':['#dependent'],'depends_on':['bad'],'operation_indexes':[2]}]}
        from remediation_interventions import coordinated_plan
        ordered,_=coordinated_plan(source,plan)
        bounded,rejected=constrain_plan(source,ordered,approach(3,VERSION))
        self.assertEqual([op['selector']for op in bounded['operations']],['#good'])
        self.assertEqual([g['id']for g in bounded['root_causes']],['good'])
        self.assertEqual(bounded['root_causes'][0]['operation_indexes'],[0])
        self.assertEqual(len(rejected),2)

    def test_stale_or_malformed_selector_blocks_only_its_cause_and_dependents(self):
        from remediation_interventions import coordinated_plan
        source='<button id="good">Go</button><p id="dependent">Help</p>'
        for selector in ('#missing','[malformed='):
            plan={'operations':[{'action':'set_attribute','selector':selector,'name':'aria-label','value':'Missing'},
                                {'action':'set_attribute','selector':'#good','name':'aria-label','value':'Go to help'},
                                {'action':'set_attribute','selector':'#dependent','name':'role','value':'note'}],
                  'root_causes':[{'id':'bad','selectors':[selector],'depends_on':[],'operation_indexes':[0]},
                                 {'id':'good','selectors':['#good'],'depends_on':[],'operation_indexes':[1]},
                                 {'id':'dependent','selectors':['#dependent'],'depends_on':['bad'],'operation_indexes':[2]}]}
            with self.subTest(selector=selector):
                ordered,_=coordinated_plan(source,plan)
                bounded,rejected=constrain_plan(source,ordered,approach(3,VERSION))
                self.assertEqual([op['selector']for op in bounded['operations']],['#good'])
                self.assertEqual([g['id']for g in bounded['root_causes']],['good'])
                self.assertEqual(len(rejected),2)

    def test_creative_request_has_brief_capture_and_no_imposed_design(self):
        image={'type':'image_url','image_url':{'url':'data:image/png;base64,fixture'}}
        messages=generation_messages('# Shop','https://example.test/',reference_document=self.source,creative=True,page_brief={'purpose':'product','category':'commerce','metadata':'Shop description'},visual_references=[image])
        system=messages[0]['content']
        self.assertIn('freedom',system);self.assertIn('No prescribed template',system)
        self.assertNotIn('Preserve every source text verbatim',system)
        self.assertNotIn('lexicographic',system)
        self.assertEqual(messages[2]['content'],'# Shop')
        self.assertTrue(any('Shop description'in m['content']for m in messages if isinstance(m['content'],str)))
        evidence=generation_evidence(messages,'markdown','local')
        self.assertEqual(evidence['visual_reference_count'],1)
        self.assertFalse(evidence['structural_reference'])
        context=next(m['content']for m in messages if isinstance(m['content'],str)and m['content'].startswith('ACQUIRED_PAGE_CONTEXT'))
        self.assertNotIn('"structure"',context);self.assertNotIn('"source_styles"',context)
        self.assertNotIn('ACQUIRED_NATIVE_CONTROL_EVIDENCE',str(messages))
        self.assertEqual(evidence['page_context_version'],'creative-page-evidence-v2')
        with self.assertRaises(ValueError):generation_messages('# Shop','https://example.test/',creative=True,framework='bootstrap')

    def test_creative_materialization_does_not_inject_source_omissions(self):
        candidate,metadata=materialize(self.source,self.candidate,4,'https://example.test/',self.source,intervention_version=VERSION)
        self.assertNotIn('Original exact words',candidate)
        self.assertNotIn('legacy',candidate)
        self.assertEqual(metadata['resource_fallback'],[])

    def test_historical_contract_is_not_reinterpreted_as_creative(self):
        self.assertTrue(four_policy(PRESERVATION_VERSION))
        self.assertIn('Preserve original information architecture',approach(4,PRESERVATION_VERSION).instruction)
        self.assertIn('Create a new polished',approach(4,VERSION).instruction)

    def test_patch_scope_stays_distinct_and_unsafe_native_role_removal_is_blocked(self):
        source='<ul id="gallery" role="list"><li role="tabpanel">Item</li></ul>'
        op={'action':'remove_attribute','selector':'#gallery','name':'role'}
        plan,rejected=constrain_plan(source,{'operations':[op]},approach(1,VERSION),base_url='https://example.test/')
        self.assertEqual(plan['operations'],[]);self.assertIn('native list children',rejected[0]['reason'])
        replace={'action':'replace_element','selector':'#gallery','html':'<ul id="gallery"><li>Item</li></ul>'}
        self.assertTrue(constrain_plan(source,{'operations':[replace]},approach(1,VERSION))[1])
        self.assertFalse(constrain_plan(source,{'operations':[replace]},approach(3,VERSION),context={'affected_nodes':[{'selector':'#gallery','html':source,'html_truncated':False,'attributes_truncated':False}]})[1])

    def test_requested_css_declarations_become_real_scoped_rules(self):
        source='<button id="go">Go</button>'
        plan,rejected=constrain_plan(source,{'operations':[{'action':'append_css','selector':'#go','css':'color: #112233;'}]},approach(1,VERSION))
        self.assertEqual(rejected,[])
        self.assertEqual(plan['operations'][0]['css'],'#go{color: #112233;}')
        size={'action':'append_css','selector':'#go','css':'min-width:24px;'}
        self.assertTrue(constrain_plan(source,{'operations':[size]},approach(1,VERSION))[1])
        self.assertFalse(constrain_plan(source,{'operations':[size]},approach(3,VERSION))[1])
        self.assertTrue(constrain_plan(source,{'operations':[size|{'css':'min-width:100vw;'}]},approach(3,VERSION))[1])

    def test_improved_accessibility_outranks_fidelity_but_worse_proposal_cannot_replace_original(self):
        original=candidate_rank(0,{},100,4,5,90,fidelity_priority=False)
        improved=candidate_rank(0,{'text_percent':40,'links_percent':20},10,4,2,95,fidelity_priority=False)
        self.assertLess(improved,original)
        incumbent={'distance':1,'quality_rank':(1,25,-89)}
        worse={'distance':2,'quality_rank':(2,28,-88),'admissible':True}
        self.assertEqual(retain(incumbent,worse),(incumbent,False))
