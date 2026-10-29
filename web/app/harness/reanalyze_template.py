"""Standalone exported script. Input is the hashed export, never a provider."""
import csv
import json
from pathlib import Path
from analysis.statistics import kappa
from analysis.analysis import outcomes, contrasts

root=Path(__file__).parent
from analysis.provenance import verify_inputs, record_outputs
from analysis.relevance import relevance_reports
manifest=verify_inputs(root)
fixture=json.loads((root/'fixture.json').read_text());assert kappa(fixture['pairs'])['kappa']==fixture['expected_kappa']
records=json.loads((root/'records.json').read_text()); data={r['id']:r for r in records}
class EvidenceStore:
    def get(self, ident): return data[ident]
    def list(self, kind=None, campaign=None):
        return [r for r in records if (kind is None or r['kind']==kind) and (campaign is None or r['campaign']==campaign)]

store=EvidenceStore();campaign=manifest['campaign_id'];configuration=data[campaign]['data']
calls=json.loads((root/'consumption.json').read_text())
runs=outcomes(store,configuration,store.list('run_result',campaign),calls)
(root/'outcomes-reconstructed.json').write_text(json.dumps(runs,indent=2))
with (root/'runs.csv').open('w',newline='') as stream:
    fields=['run_id','page_id','condition_id','repetition','preserved_success','preservation','online_preservation','assessment_source','reference_id','axe','lighthouse','cost_usd','cost_verified','seconds','PRE','corrected_instances','introduced_instances','proposed_violations','proposed_unverified']
    writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(runs)
paired=[]
for i,a in enumerate(sorted({r['condition_id'] for r in runs})):
    for b in sorted({r['condition_id'] for r in runs})[i+1:]:
        metrics=contrasts(runs,a,b)
        paired.append({'first':a,'second':b,'preserved_success':metrics['preserved_success'],'metrics':metrics})
(root/'paired-reconstructed.json').write_text(json.dumps(paired,indent=2))
(root/'rag-reconstructed.json').write_text(json.dumps(relevance_reports(store,campaign),indent=2,allow_nan=False))
from analysis.model_tasks import report as model_task_report
(root/'model-tasks-reconstructed.json').write_text(json.dumps(model_task_report(store,campaign,calls),indent=2))
record_outputs(root,['model-tasks-reconstructed.json','runs.csv','outcomes-reconstructed.json','paired-reconstructed.json','rag-reconstructed.json'],'reanalyze.py',data)
print('Verified hashes and fixture; reconstructed runs.csv, outcomes-reconstructed.json, paired-reconstructed.json, rag-reconstructed.json and PROVENANCE.json')
