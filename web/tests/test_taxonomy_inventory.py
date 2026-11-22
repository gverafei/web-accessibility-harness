import json
import tempfile
import unittest
from unittest.mock import Mock
from accessibility_taxonomy.inventory import inventory
from accessibility_taxonomy import compare
from accessibility_taxonomy.assessment import assess, measure_pair
from harness.store import Store
from harness.worker_profile import validate
from harness.contracts import ContractError

class InventoryTests(unittest.TestCase):
    def test_multilingual_declarations_use_their_own_passage_not_parent_translations(self):
        html='<html lang="en"><body>Hello <p lang="es">Hola <span lang="fr">Bonjour</span></p><p lang="ar">مرحبا</p><script>fake prose</script><!-- fake prose --></body></html>'
        rows=[r for r in inventory(html,{},'https://example.org/')['opportunities'] if r['type'] in ('lang-mismatch','language-of-parts-mismatch')]
        scoped={r['context']['element']['attributes']['lang']:r['context']['observed_text'] for r in rows}
        self.assertEqual(scoped,{'en':'Hello','es':'Hola','fr':'Bonjour','ar':'مرحبا'})
        self.assertTrue(all(r['context']['element']['text']==r['context']['observed_text'] for r in rows))

    def test_empty_language_scope_does_not_borrow_foreign_passage_text(self):
        rows=inventory('<html lang="en"><body><p lang="es">Hola</p></body></html>',{},'https://example.org/')['opportunities']
        page=next(r for r in rows if r['type']=='lang-mismatch')
        self.assertEqual(page['context']['observed_text'],'')

    def test_uncertain_measurement_consumption_cannot_be_hidden_as_missing_score(self):
        from unittest.mock import patch
        from harness.providers import UncertainCall
        with patch('accessibility_taxonomy.assessment.assess',side_effect=UncertainCall('unreconciled')):
            with self.assertRaises(UncertainCall):measure_pair(None,None,'run',{'id':'a'},{'id':'b'},'https://example.org/',{})

    def test_closed_census_does_not_claim_image_or_button_task_evidence(self):
        r=inventory('<html lang="en"><title>Help</title><body><img src="a.png" alt="Photo"><button>Send</button><h1>Help</h1></body></html>',{},'https://example.org/')
        self.assertEqual(len(r['type_coverage']),99)
        for item in r['opportunities']:
            if item['type'] in ('image-alt-not-descriptive','button-label-mismatch'):
                self.assertEqual(item['method'],'decisions' if item['type']=='button-label-mismatch' else 'unobserved_supplement')
                self.assertEqual(item['status'],'insufficient_evidence')
                if item['type']=='button-label-mismatch':
                    self.assertIn('observed_purpose',item['context'])
        self.assertIn('lang-mismatch',{r['type'] for r in r['opportunities'] if r['method']=='decisions'})
    def test_identity_survives_new_sibling_and_label_change_but_not_removed_control(self):
        axe={'violations':[{'id':'button-name','tags':['wcag412'],'nodes':[{'target':['#send']}]}]}
        before=inventory('<button id="send"></button>',axe,'https://example.org/')
        after=inventory('<div>New</div><button id="send">Send</button>',{'passes':axe['violations']},'https://example.org/')
        compared=compare(before['opportunities'],after['opportunities'])
        self.assertEqual(compared['categories']['Syntactic']['resolved'],1)
        removed=inventory('<div>New</div>',{},'https://example.org/')
        self.assertGreater(len(compare(before['opportunities'],removed['opportunities'])['excluded_original_ids']),0)
    def test_duplicate_elements_are_distinct_and_do_not_force_cross_document_match(self):
        a=inventory('<a href="/">Home</a><a href="/">Home</a>',{},'https://example.org/')
        b=inventory('<b>New</b><a href="/">Home</a><a href="/">Home</a>',{},'https://example.org/')
        self.assertEqual(len(a['opportunities']),2)
        self.assertEqual(len(compare(a['opportunities'],b['opportunities'])['excluded_original_ids']),2)
    def test_axe_selector_uses_unmodified_document_tree_and_best_practices_are_separate(self):
        html='<html><head><script></script></head><body><script></script><img></body></html>'
        axe={'violations':[{'id':'image-alt','tags':['wcag111'],'nodes':[{'target':['body > img:nth-child(2)']}]},
                           {'id':'region','tags':['best-practice'],'nodes':[{'target':['body']}]}]}
        r=inventory(html,axe,'https://example.org/')
        self.assertEqual(len(r['opportunities']),1)
        self.assertFalse(r['opportunities'][0]['identity_basis'].startswith('unmatched'))
    def test_complete_context_over_bound_abstains_without_truncating(self):
        r=inventory('<html lang="en"><body>'+'a'*30000+'</body></html>',{},'https://example.org/')
        row=r['opportunities'][0]
        self.assertEqual(row['method'],'unobserved_supplement')
        self.assertEqual(row['status'],'insufficient_evidence')
    def test_haiku_light_and_high_are_approved_without_widening_other_efforts(self):
        for effort in ('low', 'high'):
            validate([{'provider':'openrouter', 'model':'anthropic/claude-haiku-5.5',
                       'reasoning_effort':effort}])

    def test_authorized_effort_extensions_are_admitted_explicitly(self):
        for model, effort in [('anthropic/claude-sonnet-5.5','low'), ('anthropic/claude-sonnet-5.5','high'), ('anthropic/claude-opus-5.5','high'), ('openai/gpt-6-astra','high'), ('openai/gpt-6.1-sol','high'),
                              ('openai/gpt-6-luna','medium'), ('openai/gpt-6-luna','xhigh')]:
            validate([{'provider':'openrouter','model':model,'reasoning_effort':effort}])

    def test_unapproved_worker_configuration_is_rejected(self):
        for model,effort in [('anthropic/claude-sonnet-5.5','medium'),('anthropic/claude-haiku-5.5','medium'),('openai/gpt-6.1-sol','medium'),('openai/gpt-6-luna',None)]:
            with self.assertRaises(ContractError):validate([{'model':model,'reasoning_effort':effort}])
        validate([{'model':'openai/gpt-6-luna','reasoning_effort':'high'}])
        validate([{'model':'anthropic/claude-haiku-5.5','reasoning_effort':'low'}])
    def test_assessment_is_blinded_cached_and_does_not_need_optional_confidence(self):
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);p=Mock(campaign='fixture')
            p.ledger.rows.return_value=[]
            p.decisions.side_effect=lambda run,account,key,evidence,questions,**kw:{q['name']:{'type':'choice','choice':'passed'} for q in questions}
            html=store.blob('<html lang="en"><head><title>Help</title></head><body>Help</body></html>','rendered','fixture','text/html')
            axe=store.blob('{}','axe','fixture','application/json')
            audit=store.append('audit',{'status':'completed','artifacts':{'rendered':html['id'],'axe':axe['id']}},'fixture')
            result=assess(store,p,'run',audit,'https://example.org/',{'model':'fixture'})
            again=assess(store,p,'other-run',audit,'https://example.org/',{'model':'fixture'})
            self.assertEqual(result['id'],again['id']);p.decisions.assert_called_once()
            self.assertNotIn('worker',p.decisions.call_args.args[3]);self.assertNotIn('level',p.decisions.call_args.args[3])
            out=measure_pair(store,p,'run',audit,audit,'https://example.org/',{'model':'fixture'})
            self.assertEqual(out['original_assessment_id'],out['retained_assessment_id'])

    def test_acquired_image_bytes_are_bound_to_blinded_question_and_budget_account(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);p=Mock(campaign='fixture');p.ledger.rows.return_value=[]
            p.manifest={'workers':[{'model':'openai/gpt-6-luna','reasoning_effort':'low','vision':True}]}
            import json
            def visual_answer(*args,**kwargs):
                question=json.loads(args[4].split('\n')[-1])['opportunities'][0]
                return json.dumps({'judgments':[{'opportunity_id':question['opportunity_id'],'status':'passed'}]})
            p.chat.side_effect=visual_answer
            p.decisions.side_effect=lambda run,account,key,evidence,questions,**kw:{q['name']:{'type':'choice','choice':'passed'} for q in questions}
            html=store.blob('<img src="/photo.png" alt="A mountain">','rendered','fixture','text/html')
            axe=store.blob('{}','axe','fixture','application/json')
            import io
            from PIL import Image
            buffer = io.BytesIO()
            Image.new('RGB', (32, 24), 'navy').save(buffer, format='PNG')
            image_bytes = buffer.getvalue()
            image=store.blob(image_bytes,'image','fixture','image/png')
            asset={'url':'https://example.org/photo.png','mime':'image/png','artifact_id':image['id'],'sha256':hashlib.sha256(image_bytes).hexdigest()}
            capture={'data':{'assets':[asset]}}
            audit=store.append('audit',{'status':'completed','artifacts':{'rendered':html['id'],'axe':axe['id']}},'fixture')
            row=assess(store,p,'run',audit,'https://example.org/',{'model':'fixture','vision':True},capture)
            self.assertEqual(row['data']['opportunities'][0]['status'],'passed')
            self.assertEqual(p.chat.call_args.args[1],'review')
            self.assertEqual(len(p.chat.call_args.kwargs['image_parts']),1)
            self.assertIn(asset['sha256'],p.chat.call_args.args[4])
            asset['sha256']='0'*64
            with self.assertRaises(ContractError):assess(store,p,'run',audit,'https://example.org/',{'model':'fixture','vision':True},capture)
            p.chat.assert_called_once();p.decisions.assert_not_called()
    def test_unmapped_wcag_rule_is_retained_as_unclassified(self):
        r=inventory('<button id="b">OK</button>',{'violations':[{'id':'future-rule','tags':['wcag412'],'impact':'serious','nodes':[{'target':['#b']}]}]},'https://example.org/')
        self.assertEqual(r['unmapped_axe_rules'],['future-rule'])
        self.assertEqual(r['summary']['categories']['Unclassified']['failed'],1)

class SettledInterstitialTests(unittest.TestCase):
    def test_earlier_anubis_response_uses_settled_native_document(self):
        from harness.source_preparation import prepare
        from harness.capture_admission import assess
        challenge='<html><head><title>Making sure you are not a bot!</title><script id="anubis_challenge">{}</script></head><body><main>wait</main></body></html>'
        native='<html><head><title>Library</title></head><body><main><h1>Library</h1>'+('<p>Collection</p>'*10)+'</main></body></html>'
        html,metadata=prepare(challenge,native,'https://example.org/')
        self.assertEqual(metadata['selection']['adapter'],'settled-interstitial-v1')
        self.assertIn('Library',html)
        self.assertIn('anubis_challenge',assess(challenge,{})['reasons'])
        # A still challenged DOM cannot turn an invalid acquisition into content.
        html,metadata=prepare(challenge,challenge,'https://example.org/')
        self.assertNotEqual(metadata['selection'].get('adapter'),'settled-interstitial-v1')
        self.assertIn('anubis_challenge',assess(html,{})['reasons'])

class BlindedContextTests(unittest.TestCase):
    def test_context_contains_target_text_and_associated_form_label(self):
        from accessibility_taxonomy.inventory import inventory
        rows=inventory('<html><head><title>Library catalog</title></head><body><label for="q">Search catalog</label><input id="q" name="query"><h1>Library collections</h1></body></html>',{},'https://example.org/')['opportunities']
        heading=next(r for r in rows if r['type']=='heading-not-descriptive')
        form=next(r for r in rows if r['type']=='form-label-mismatch')
        self.assertEqual(heading['context']['element']['text'],'Library collections')
        self.assertEqual(form['context']['element']['labels'],['Search catalog'])


class PagePurposeScopeTests(unittest.TestCase):
    def test_title_context_excludes_title_and_script_from_full_body(self):
        row=next(r for r in inventory('<html><head><title>Wrong title</title></head><body><h1>Library</h1><p>Opening hours</p><script>Recipe</script></body></html>',{},'https://controls.invalid/')['opportunities'] if r['type']=='page-title-not-descriptive')
        self.assertEqual(row['context']['observed_text'],'Library Opening hours')
        self.assertIn('Complete text',row['context']['content_scope'])

class BypassApplicabilityTests(unittest.TestCase):
 def test_simple_document_abstention_is_not_missing_skip_failure(self):
  from accessibility_taxonomy.inventory import inventory
  axe={'incomplete':[{'id':'bypass','tags':['wcag241'],'nodes':[{'target':['html']}]}]}
  html='<html><body><p>Example domain information</p><a href="/help">Learn more</a></body></html>'
  row=next(r for r in inventory(html,axe,'https://example.org/')['opportunities'] if r['type']=='bypass')
  self.assertEqual(row['status'],'not_applicable')
  self.assertEqual(row['method'],'snapshot_bypass_applicability')
  self.assertEqual(row['supplementary_evidence']['link_count'],1)
  for body in ('<nav><a href="/one">One</a><a href="/two">Two</a></nav><p>Content</p>', '<div>Opaque shared block</div><p>Content</p>', '<p><a href="/a">One</a><a href="/b">Two</a></p>'):
   row=next(r for r in inventory('<html><body>'+body+'</body></html>',axe,'https://example.org/')['opportunities'] if r['type']=='bypass')
   self.assertEqual(row['status'],'insufficient_evidence')
