"""Explicit UI simulation. No persistence, provider, acquisition or evaluator API."""
import random
from remediation_report_presentation import event_presentation, live_loop_participants
STEPS=(
 ('acquire','Acquisition',None,'Load the reference page'),
 ('transform','Transformer',None,'Prepare page context'),
 ('extraction_quality','Acquisition quality specialist',None,'Check the captured evidence'),
 ('decisions_call','Decisions agent','Page classification','Identify the page purpose'),
 ('rag_retrieval','RAG-ACT retriever',None,'Retrieve relevant accessibility examples'),
 ('decisions_call','Decisions agent','RAG example relevance','Choose relevant examples'),
 ('decisions_call','Decisions agent','Level and model selection','Choose the intervention and model'),
 ('skill_orchestration','Skill orchestrator',None,'Activate the repair procedures'),
 ('generate','Generator',None,'Request a candidate from the model'),
 ('generate','Generator',None,'Receive the generated candidate'),
 ('patch','Patch executor',None,'Apply the proposed intervention'),
 ('evaluate','Evaluation team',None,'Measure accessibility with Axe and Lighthouse'),
 ('decisions_call','Decisions agent','Semantic evaluation','Evaluate a batch of semantic cases'),
 ('llm_call','Image-purpose judge','Complementary taxonomy evaluation','Review accessible image alternatives'),
 ('decisions_call','Decisions agent','Complementary taxonomy evaluation','Complete contrast judgments'),
 ('llm_call','Visual review agent','Capture verification','Review the visible candidate'),
 ('decision','Acceptance coordinator',None,'Compare the measured candidates'),
 ('accepted','Acceptance coordinator',None,'Keep the chosen candidate'),
 ('refine','Acceptance coordinator',None,'Return feedback for refinement'),
)
def scenario(seed,cycle):
 rng=random.Random(int(seed)+cycle*7919)
 steps=list(STEPS[:-2])
 # Change parallel-observation order and bounded refinement routes in the demo only.
 if rng.choice((True,False)):steps[12:15]=[steps[13],steps[12],steps[14]]
 for _ in range(rng.randrange(3)):
  steps.extend([STEPS[18],STEPS[5],STEPS[8],STEPS[9],STEPS[11],STEPS[15],STEPS[16]])
 steps.append(STEPS[17])
 return steps

def frame(index,seed=0):
 index=max(0,min(100000,int(index)));cycle=0;steps=scenario(seed,cycle)
 while index>=len(steps):index-=len(steps);cycle+=1;steps=scenario(seed,cycle)
 step=index;events=[]
 for number,(kind,actor,role,message) in enumerate(steps[:step+1]):
  llm=kind in ('decisions_call','llm_call')
  event={'id':f'demo-{cycle}-{number}','event_type':kind,'actor':actor,'message':message,
         'decision_role':role,'decision_cases':[{}]*20 if role=='Semantic evaluation' else [],
         'details_json':{'model':'openai/gpt-6-luna-decisions'if actor=='Decisions agent'else'openai/gpt-6-luna'}if llm else{}}
  event_presentation(event);events.append(event)
 run={'id':0,'status':'running','live_demo':True,'current_phase':'generate','current_iteration':cycle+1,'max_iterations':'∞','progress_percent':round(100*step/(len(steps)-1)),
      'progress_message':steps[step][3],'total_cost_usd':0,'dynamic_level':True,'execution_mode':'iterative',
      'live_participants':live_loop_participants(events),'live_taxonomy_progress':{'status':'running'if step in (12,13,14)else'completed','stage':'contextual','completed':(step-11)*20 if step in (12,13,14)else 0,'total':60}if step in (12,13,14)else{}}
 kind,actor,role,message=steps[step]
 run['execution_counts']={'evaluated':0,'attempts':cycle+1,'limit':'∞'}
 if actor in ('Generator','Decisions agent','Image-purpose judge','Visual review agent'):
  stage={'Page classification':'context','RAG example relevance':'evidence','Level and model selection':'selection','Capture verification':'preserve'}.get(role,'taxonomy'if kind in ('llm_call','decisions_call')else'repair')
  pending=message.startswith('Request') or kind in ('llm_call','decisions_call')
  call={'id':f'demo-call-{cycle}-{step}','stage':stage,'vendor':'OpenAI','provider':'OpenRouter','model':'openai/gpt-6-luna','pending':pending,'returned':not pending,'status':'dispatching'if pending else'received'}
  run['live_provider_activity']={'active':[call]if pending else[],'latest':call}
 # This overlap is explicitly simulated; the production view requires real pending receipts.
 if step==12:
  other={'id':f'demo-overlap-{cycle}-{step}','stage':'preserve','vendor':'OpenAI','provider':'OpenRouter','model':'openai/gpt-6-luna','pending':True,'returned':False,'status':'dispatching'}
  run.setdefault('live_provider_activity',{'active':[],'latest':other})['active'].append(other)
 return run,events,[]
