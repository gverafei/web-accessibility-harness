import unittest
from remediation_live_events import change_stream

class LiveEventsTests(unittest.TestCase):
 def test_emits_only_recorded_changes_and_final_state(self):
  states=iter([{'status':'running','event':1},{'status':'running','event':1},
               {'status':'running','event':2},{'status':'accepted','event':3}])
  now=[0]
  def sleep(seconds):now[0]+=seconds
  rows=list(change_stream(lambda:next(states),clock=lambda:now[0],sleep=sleep))
  self.assertEqual(len(rows),3)
  self.assertTrue(all(row.startswith('event: activity\n')for row in rows))
  self.assertEqual(len(set(rows)),3)
 def test_no_missing_run_or_fabricated_idle_progress(self):
  self.assertEqual(list(change_stream(lambda:None)),[])
  now=[0]
  rows=list(change_stream(lambda:{'status':'running'},duration=1,interval=.25,
      clock=lambda:now[0],sleep=lambda seconds:now.__setitem__(0,now[0]+seconds)))
  self.assertEqual(len(rows),1)
