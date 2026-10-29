import copy
import unittest
from harness.replay_admission import compare


class WorkerMetadataAdmissionTests(unittest.TestCase):
    def evidence(self):
        return {'text':'A sufficiently long original visible page description with multiple controls and meaningful retained content to inspect.',
                'controls':[], 'visible_images':1, 'visible_media':1, 'broken_media':0,
                'media_evidence_version':'observed-media-state-v4',
                'media_descriptors':[{'state':'metadata','identity':{'kind':'VIDEO','sources':[]},
                    'src_object_kind':'MediaSourceHandle','ready_state':1,'network_state':2,
                    'current_time':0,'paused':True,'error':None,'video_width':640,'video_height':360,'buffered_ranges':[]}]}

    def test_exact_metadata_preservation_and_raw_regressions(self):
        original=self.evidence()
        self.assertEqual(compare(original,copy.deepcopy(original))['status'],'admitted')
        for key,value in [('video_width',0),('ready_state',0),('network_state',0),('current_time',1),('error',3),('buffered_ranges',[[0,1]])]:
            replay=copy.deepcopy(original)
            replay['media_descriptors'][0][key]=value
            self.assertIn('worker_metadata_state_changed',compare(original,replay)['reasons'])

    def test_loss_cannot_be_reclassified_as_waiting_or_legacy_evidence(self):
        original=self.evidence()
        replay=copy.deepcopy(original)
        replay['media_descriptors'][0]['state']='deferred'
        self.assertEqual(compare(original,replay)['status'],'rejected')
        original['media_evidence_version']='observed-media-state-v3'
        self.assertIn('missing_original_worker_metadata_evidence',compare(original,self.evidence())['reasons'])
