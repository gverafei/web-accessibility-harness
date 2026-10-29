import unittest
from harness.replay_admission import compare
class MediaAdmissionTests(unittest.TestCase):
 def test_missing_or_broken_media_is_not_hidden_by_complete_text_and_images(self):
  original={'text':'A complete page with enough words to be reviewed safely','controls':[],'visible_images':1,'visible_media':1}
  for addition,reason in [({'visible_media':0},'visible_media_loss'),({'visible_media':1,'broken_media':1},'broken_visible_media')]:
   result=compare(original,{**original,**addition})
   self.assertEqual(result['status'],'rejected');self.assertIn(reason,result['reasons'])
  self.assertEqual(compare(original,original)['status'],'admitted')
 def test_deferred_media_requires_original_matching_state_not_just_a_preload_attribute(self):
  descriptor={'identity':{'kind':'VIDEO','preload':'none','poster':'','sources':['https://example.org/video.mp4']},'state':'deferred'}
  page={'text':'Known original content with a deferred authored video','controls':[],'visible_images':1,'visible_media':1,'broken_media':0,'deferred_media':1,'media_evidence_version':'observed-media-state-v2','media_descriptors':[descriptor]}
  self.assertEqual(compare(page,page)['status'],'admitted')
  for original in [{**page,'media_descriptors':[{**descriptor,'state':'loaded'}]}, {**page,'media_descriptors':[]}]:
   result=compare(original,page);self.assertEqual(result['status'],'rejected');self.assertIn('newly_deferred_media',result['reasons'])
  legacy={k:v for k,v in page.items() if k not in ['media_evidence_version','media_descriptors']}
  result=compare(legacy,page);self.assertEqual(result['status'],'review_required');self.assertIn('missing_original_deferred_media_evidence',result['reasons'])
  duplicate={**page,'visible_media':2,'deferred_media':2,'media_descriptors':[descriptor,descriptor]}
  self.assertIn('newly_deferred_media',compare(page,duplicate)['reasons'])

 def test_unbuffered_media_matches_only_observed_original_state_without_claiming_playback(self):
  descriptor={'identity':{'kind':'VIDEO','sources':['https://example.org/video.m3u8']},'state':'unbuffered','media_source':{'version':'observed-media-source-v1','ready_state':'open','buffers':0}}
  page={'text':'Observed original content with a waiting media source','visible_images':1,'visible_media':1,'broken_media':0,'media_evidence_version':'observed-media-state-v3','media_descriptors':[descriptor]}
  self.assertEqual(compare(page,page)['status'],'admitted')
  self.assertIn('unbuffered_original_media_preserved_playback_not_assessed',compare(page,page)['warnings'])
  for state in ['loaded','broken','deferred']:
   original={**page,'media_descriptors':[{**descriptor,'state':state}]}
   self.assertIn('newly_unbuffered_media',compare(original,page)['reasons'])
   self.assertNotIn('unbuffered_original_media_preserved_playback_not_assessed',compare(original,page)['warnings'])
  legacy={**page,'media_evidence_version':'observed-media-state-v2'}
  self.assertEqual(compare(legacy,page)['status'],'review_required')
  duplicate={**page,'media_descriptors':[descriptor,descriptor]}
  self.assertIn('newly_unbuffered_media',compare(page,duplicate)['reasons'])
  invalid={**page,'media_descriptors':[{**descriptor,'media_source':None}]}
  self.assertIn('newly_unbuffered_media',compare(page,invalid)['reasons'])
