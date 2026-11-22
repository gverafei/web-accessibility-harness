import os
import unittest
from flask import render_template
from accessibility_taxonomy.presentation import counts

os.environ['HARNESS_TESTING']='1'


class TaxonomyPresentationTests(unittest.TestCase):
    def setUp(self):
        self.measurement={'original':{'categories':{
            'Syntactic':{'failed':4,'judged':115,'unassessed':2,'observed_burden':18},
            'Semantic':{'failed':2,'judged':17,'unassessed':71,'observed_burden':6},
            'Layout':{'failed':39,'judged':132,'unassessed':4,'observed_burden':156}}},
            'retained':{'categories':{
            'Syntactic':{'failed':0,'judged':123,'unassessed':2,'observed_burden':0},
            'Semantic':{'failed':4,'judged':16,'unassessed':75,'observed_burden':16},
            'Layout':{'failed':13,'judged':152,'unassessed':4,'observed_burden':52}}}}

    def test_display_uses_full_detected_counts_not_severity_or_matched_subset(self):
        rows=counts(self.measurement)
        self.assertEqual([(r['before'],r['after']) for r in rows],[(4,0),(2,4),(39,13)])
        self.assertTrue(all(r['partial'] for r in rows))

    def test_unjudged_cases_are_not_measured_zeros(self):
        m={'summary':{'categories':{'Semantic':{'failed':0,'judged':0,'unassessed':12}}}}
        self.assertIsNone(counts(m)[1]['before'])
        self.assertIsNone(counts(m)[1]['after'])
        self.assertTrue(counts(m)[1]['partial'])
        self.assertTrue(all(r['before'] is None for r in counts(None)))

    def test_report_and_list_share_counts_and_do_not_display_weighted_burden(self):
        from main import create_app
        app=create_app({'TESTING':True})
        with app.test_request_context():
            html=render_template('_taxonomy_outcomes.html',measurement=self.measurement,taxonomy_number=2)
            compact=render_template('_taxonomy_counts.html',measurement=self.measurement)
        self.assertIn('<td>39</td>',html);self.assertIn('<td>13</td>',html)
        self.assertIn('39 → 13',compact)
        self.assertNotIn('156',html);self.assertNotIn('Original burden',html)
        self.assertIn('section-number',html)

    def test_missing_and_failed_measurement_render_without_inventing_counts(self):
        from main import create_app
        app=create_app({'TESTING':True})
        with app.test_request_context():
            for measurement in (None,{'status':'not_assessed','errors':['No evidence']}):
                html=render_template('_taxonomy_outcomes.html',measurement=measurement,taxonomy_number=2)
                self.assertNotIn('<td>0</td>',html)


    def test_details_preserve_detector_counts_and_exact_targets(self):
        from accessibility_taxonomy.presentation import details
        from unittest.mock import Mock
        store=Mock()
        store.get.side_effect=lambda ident:{'data':{'model':{'model':'openai/gpt-6-luna-decisions'},'opportunities':[
            {'type':'color-contrast','method':'axe','status':'failed','target':['#title']},
            {'type':'lang-mismatch','method':'decisions','status':'failed' if ident=='a' else 'passed','context':{'element':{'text':'Welcome'}}}]}}
        result=details({'original_assessment_id':'a','retained_assessment_id':'b'},store)
        self.assertEqual(sum(r['before'] for r in result['rows']),2)
        self.assertEqual(sum(r['after'] for r in result['rows']),1)
        self.assertEqual({r['detector'] for r in result['rows']},{'Axe','Decisions Luna'})
        self.assertEqual(next(r for r in result['rows'] if r['type']=='color-contrast')['evidence'][0]['target'],'#title')

    def test_missing_detail_never_invents_detectors(self):
        from accessibility_taxonomy.presentation import details
        from unittest.mock import Mock
        store=Mock();store.get.side_effect=KeyError('missing')
        result=details({'original_assessment_id':'missing'},store)
        self.assertEqual(result['rows'],[]);self.assertEqual(result['missing'],['original'])

    def test_iteration_distinguishes_checkpoint_from_final_retention(self):
        from main import create_app
        app=create_app({'TESTING':True})
        item={'id':168,'iteration_number':4,'candidate_key':'ddaa7faf','decision':'refine','generator_model':'luna','targets_met':False,'axe_violations':18,'lighthouse_score':96,'technical_status':'passed','input_tokens':10,'output_tokens':2,'cost_usd':.001,'execution_seconds':4,'strategy':{'assigned_level':1,'harness':{'retained':True}}}
        with app.test_request_context():
            html=render_template('_remediation_iteration_overview.html',item=item,run={'dynamic_level':True,'max_axe':5,'min_lighthouse':90},best={'id':169})
            final=render_template('_remediation_iteration_overview.html',item=item,run={'dynamic_level':True,'max_axe':5,'min_lighthouse':90},best={'id':168})
        self.assertIn('Best result at this iteration',html)
        self.assertNotIn('Final retained candidate',html)
        self.assertIn('Final retained candidate',final)
        self.assertIn('data-chosen-iteration="168"',final)
        self.assertIn('✓ Chosen',final)
        self.assertNotIn('data-chosen-iteration',html)
        self.assertIn('Technical validity is separate',html)

    def test_chosen_technically_valid_candidate_keeps_visual_rejection_and_rationale_visible(self):
        from main import create_app
        from remediation_report_presentation import target_presentation
        from bs4 import BeautifulSoup
        app = create_app({'TESTING':True})
        item = {'id':2892,'display_iteration_number':1,'decision':'refine',
                'axe_violations':0,'lighthouse_score':100,'input_tokens':0,'output_tokens':0,
                'cost_usd':0,'execution_seconds':0,'strategy':{'harness':{'retained':True,
                'assessment':{'status':'passed','checks':{
                    'capture_verification':{'status':'rejected','evidence_refs':['saved-review'],
                        'rationale':'Top images load, but the resource inventory reports missing covers.'},
                    'candidate_usability':{'status':'rejected','metrics':{'broken_images':12},
                        'reasons':['broken_visible_resources']}}}}}}
        run = {'max_axe':5,'min_lighthouse':90,'visual_review_diagnostic':True}
        target_presentation(run,item)
        with app.test_request_context():
            page = BeautifulSoup(render_template('_remediation_iteration_overview.html',
                item=item,run=run,best={'id':2892}),'html.parser')
            findings = BeautifulSoup(render_template('_remediation_iteration_validation.html',
                item=item),'html.parser')
        self.assertEqual(page.select_one('[data-visual-status]')['data-visual-status'],'rejected')
        visual = page.select_one('[data-visual-status]')
        self.assertEqual(visual.select_one('[data-visual-decision]').get_text(),'Not accepted')
        self.assertIn('resource inventory reports missing covers',visual.select_one('[data-visual-rationale]').get_text())
        self.assertFalse(visual.select('a'))
        self.assertFalse(page.select('#validation-2892'))
        self.assertFalse(findings.select_one('#validation-2892').has_attr('open'))
        self.assertNotIn('resource inventory reports missing covers',findings.get_text())
        self.assertNotIn('Visual verification rejected',findings.get_text())
        self.assertIn('recorded resource inventory',findings.get_text())
        self.assertIn('did not block candidate selection',page.get_text())
        self.assertTrue(page.select_one('[data-chosen-iteration="2892"]'))
        self.assertEqual(item['technical_status'],'passed')
        # Legacy precheck rejections can lack both metrics and a visual call.
        item['strategy']['harness']['assessment']['checks'] = {
            'capture_verification':{'status':'rejected'},
            'candidate_usability':{'status':'rejected','reasons':[]}}
        target_presentation(run,item)
        with app.test_request_context():
            blocked = render_template('_remediation_iteration_overview.html',item=item,run=run,best={'id':2892})
        self.assertIn('Not performed',blocked)
        self.assertIn('Visual review was not performed',blocked)

    def test_visual_verdict_rationale_is_escaped_and_missing_reviews_stay_distinct(self):
        from main import create_app
        from remediation_report_presentation import target_presentation
        from bs4 import BeautifulSoup
        app = create_app({'TESTING':True})
        item = {'id':2,'input_tokens':0,'output_tokens':0,'cost_usd':0,'execution_seconds':0,
                'strategy':{'harness':{'assessment':{'checks':{
            'capture_verification':{'status':'admitted','rationale':'<script>saved rationale</script>'}}}}}}
        with app.test_request_context():
            target_presentation({},item)
            page = BeautifulSoup(render_template('_remediation_iteration_overview.html',
                item=item,run={},best=None),'html.parser')
            self.assertIn('<script>saved rationale</script>',page.select_one('[data-visual-rationale]').get_text())
            self.assertFalse(page.select_one('[data-visual-status]').select('script'))
            item['strategy']['harness']['assessment']['checks'] = {}
            target_presentation({},item)
            missing = BeautifulSoup(render_template('_remediation_iteration_overview.html',
                item=item,run={},best=None),'html.parser')
            self.assertEqual(missing.select_one('[data-visual-status]')['data-visual-status'],'not_recorded')
            self.assertEqual(missing.select_one('[data-visual-decision]').get_text(),'Not recorded')

    def test_visual_card_does_not_invent_a_review_from_a_precheck_rejection_or_absence(self):
        from remediation_report_presentation import visual_review_presentation
        self.assertEqual(visual_review_presentation({}),{'status':'not_recorded','recorded':False})
        blocked = {'capture_verification':{'status':'rejected'},'candidate_usability':{'status':'rejected'}}
        self.assertEqual(visual_review_presentation(blocked)['status'],'not_performed')
        self.assertEqual(visual_review_presentation({'capture_verification':{'status':'admitted'}})['status'],'admitted')
        self.assertEqual(visual_review_presentation({'capture_verification':{'status':'review_required'}})['status'],'review_required')

    def test_chosen_marker_tracks_selected_id_not_position_or_checkpoint(self):
        from main import create_app
        app=create_app({'TESTING':True})
        base={'strategy':{'harness':{'retained':True}},'decision':'accept','targets_met':True,
              'generator_model':'luna','technical_status':'passed','axe_violations':0,
              'lighthouse_score':100,'input_tokens':0,'output_tokens':0,'cost_usd':0,'execution_seconds':0}
        items=[dict(base,id=n,iteration_number=n) for n in (1,2,3)]
        with app.test_request_context():
            for chosen in (1,2,3,None):
                html=''.join(render_template('_remediation_iteration_overview.html',item=item,
                    run={'max_axe':5,'min_lighthouse':90},best={'id':chosen}) for item in items)
                self.assertEqual(html.count('data-chosen-iteration='), int(chosen is not None))
                if chosen:self.assertIn('data-chosen-iteration="'+str(chosen)+'"',html)

    def test_progress_names_actual_retained_iteration_and_keeps_failures_visible(self):
        from remediation_report_presentation import retained_progress
        run={'status':'accepted','accepted_iteration_id':327,'current_iteration':5}
        self.assertEqual(retained_progress(run,1,0,100),'Iteration 1 chosen · Axe 0 · Lighthouse 100')
        self.assertEqual(retained_progress(run,2,None,95),'Iteration 2 chosen · Axe — · Lighthouse 95')
        for status in ('queued','running','failed'):
            self.assertEqual(retained_progress(run|{'status':status,'progress_message':'Actual failure'},1,0,100),'Actual failure')
        original={'status':'completed_with_warnings','harness_outcome':{'selected':{'original':True}}}
        self.assertEqual(retained_progress(original,None,5,88),'Original retained · Axe 5 · Lighthouse 88')
        self.assertEqual(retained_progress(run|{'progress_message':'No recorded number'},None,0,100),'No recorded number')

    def test_detector_evidence_is_escaped_in_detail(self):
        from main import create_app
        app=create_app({'TESTING':True})
        rows=[{'category':'Syntactic','type':'image-alt','detector':'Axe','before':1,'after':0,'evidence':[{'phase':'original','target':'<img onerror="attack">','text':''}]}]
        with app.test_request_context():
            html=render_template('_taxonomy_violation_details.html',detail={'rows':rows},paired=True)
        self.assertIn('&lt;img',html);self.assertNotIn('<img onerror=',html)
