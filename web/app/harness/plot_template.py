"""Optional export plot. Requires matplotlib; no figures are created without observed data."""
import json
from pathlib import Path
import matplotlib.pyplot as plt
from analysis.provenance import verify_inputs, record_outputs, sha
root=Path(__file__).parent
verify_inputs(root)
provenance=json.loads((root/'PROVENANCE.json').read_text())
if sha(root/'paired-reconstructed.json')!=provenance['outputs']['paired-reconstructed.json']['sha256']:
    raise SystemExit('Reconstructed paired input was changed; rerun reanalyze.py first.')
rows=json.loads((root/'paired-reconstructed.json').read_text())
rows=[r for r in rows if r['preserved_success']['interval'] is not None]
if not rows:raise SystemExit('No observed paired contrast with a defined interval; no figure generated.')
fig,ax=plt.subplots(figsize=(7,max(2,len(rows)*.45)))
for i,row in enumerate(rows):
    value=row['preserved_success'];low,high=value['interval'];mean=value['mean']
    ax.errorbar(mean,i,xerr=[[mean-low],[high-mean]],fmt='o',color='#24764c')
ax.set_yticks(range(len(rows)),[r['second']+' − '+r['first'] for r in rows]);ax.axvline(0,color='gray',linewidth=.7)
ax.set_xlabel('Paired change in preserved success (95% page-clustered interval)');fig.tight_layout()
fig.savefig(root/'paired-outcomes.png',dpi=1000);fig.savefig(root/'paired-outcomes.svg');plt.close(fig)

record_outputs(root,['paired-outcomes.png','paired-outcomes.svg'],'plot.py',provenance['outputs']['paired-reconstructed.json']['record_ids'],append=True)
