"""Offline projection of recorded Decisions calls, never provider activity."""
import json,tempfile,unittest
from datetime import datetime
from harness.store import Store
from harness.providers import Ledger
from remediation_report_presentation import decision_activity_events,event_presentation
class DecisionsTraceTests(unittest.TestCase):
 def test_receipts_project_with_choices_usage_and_model_without_mutation(self):
  with tempfile.TemporaryDirectory() as directory:
   store=Store(directory);Ledger(store)
   request=store.append('provider_request',{'request':{'questions':[{'name':'action'}]}},'campaign',ident='request')
   store.append('decision',{'selected':'P2:worker','selector':'decisions'},'campaign',ident='sql-run-9-decision-0')
   with store.connect() as db:
    db.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",('call','sql-run-9-decision-0:selector','campaign','sql-run-9','repair',1.,.01,.0004,'provider_reported','received','hash',request['id'],None,'provider/decisions',90,0,.2,None))
   run={'id':9,'harness_config_json':json.dumps({'campaign_id':'campaign'})}
   originals=[{'created_at':datetime(1970,1,1),'actor':'Software','event_type':'acquire','message':'source'}]
   before=store.list();events=decision_activity_events(run,originals,store,'UTC')
   self.assertEqual(len(events),2);self.assertEqual(len(originals),1);self.assertEqual(store.list(),before)
   event=events[1];event_presentation(event)
   self.assertEqual(event['actor'],'Decisions agent');self.assertEqual(event['activity_category'],'llm');self.assertEqual(event['activity_model'],'provider/decisions')
   self.assertIn('P2:worker',event['activity_message']);self.assertIn('0.000400',event['activity_message']);self.assertIn('90',event['activity_message'])
   self.assertEqual(decision_activity_events(run,events,store,'UTC'),events)
 def test_no_evidence_no_invented_agent(self):
  with tempfile.TemporaryDirectory() as directory:
   store=Store(directory)
   events=[{'id':1,'created_at':datetime(2026,1,1)}]
   self.assertEqual(decision_activity_events({'id':1},events,store,'UTC'),events)
   self.assertEqual(decision_activity_events({'id':1,'harness_config_json':'bad'},events,store,'UTC'),events)
