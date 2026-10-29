"""Paper-aligned translated display names; stored evidence values remain unchanged."""
from flask import request,url_for
from flask_babel import gettext as _

LABELS={
 'frozen':'Frozen comparison','development':'Development','validation':'Held-out validation','test':'Final evaluation',
 'rules':'Deterministic rules','decisions':'Decision model','structured':'Structured LLM selector',
 'fixed':'Fixed intervention','round_robin':'Fixed action order','initial':'Initial diagnosis only',
 'mapped':'Mapped rules and contextual ranking','legacy':'Vector-neighborhood baseline','off':'Without RAG','retrieved':'Implemented retrieval','oracle':'Validated relevant examples',
 'passed':'Preserved / correct','violated':'Verified violation','unverified':'Not verifiable','not_applicable':'Not applicable',
 'content':'Content preservation','tasks':'Task preservation','names':'Accessible names','structure':'Structural meaning',
 'preservation':'Preservation checks','retention':'Best-candidate retention','feedback':'Audit feedback','guidance':'Evidence summaries','memory':'Verified examples',
 'paused':'Paused','admitted':'Admitted','rejected':'Rejected','review_required':'Requires review','failed':'Failed','draft':'Draft','queued':'Queued','completed':'Completed','blocked':'Needs reconciliation','interrupted':'Interrupted','running':'Running','discarded':'Removed',
 'configuration':'Configuration','acquisition':'Acquisition','diagnosis':'Diagnosis','remediation':'Remediation','evaluation':'Evaluation','analysis':'Analysis',
 'author_a':'Author A','author_b':'Author B','representative':'Representative sample','enriched':'Disagreement / possible harm','all':'All cases',
 'original':'Original','candidate':'Candidate','unclassified':'Unclassified','standard':'Standard',
 'judge_0':'Judge 1','judge_1':'Judge 2','reference':'Reference','initial_judgments':'Initial judgments','revised':'Revised judgments','exploratory':'Exploratory',
 'effort_none':'No reasoning','effort_minimal':'Minimal reasoning','effort_low':'Light reasoning','effort_medium':'Medium reasoning','effort_high':'High reasoning','effort_xhigh':'Extra-high reasoning',
 'policy_validation':'Policy validation','policy_promotion':'Policy promotion','policy_rollback':'Policy rollback',
 'P1':'P1 · Minimal attributes','P2':'P2 · Localized repair','P3':'P3 · Coordinated repair','P4':'P4 · HTML regeneration','P5':'P5 · Markdown regeneration','P6':'P6 · Adaptive harness',
 'original acquired DOM':'Original source','candidate DOM':'Candidate source','candidate audit':'Candidate audit','original audit':'Original audit',
 'original and candidate DOM: identical frozen artifact':'Unchanged source','original and candidate audit: unchanged page':'Unchanged audit',
}
def display_label(value):return _(LABELS.get(str(value),str(value)))

def agreement_label(value):
    return ' · '.join(display_label('initial_judgments' if part=='initial' else part) for part in str(value).replace('--',':').split(':'))

def policy_label(row):
    data=row['data'];count=len(data['parameters']['experience_ids'])
    return (_('Learned version') if data.get('parent') else _('Initial policy'))+' · '+str(count)+' '+_('verified experiences')+' · '+row['id'][:8]

def breadcrumbs():
    endpoint=(request.endpoint or '').split('.')[-1]
    groups={'new_campaign':('campaigns','Campaigns','New campaign'),'campaign':('campaigns','Campaigns','Campaign details'),
        'run':('runs','Runs','Run details'),'review_case':('review','Review','Evidence review'),
        'relevance':('knowledge','Knowledge','Relevance reference')}
    if endpoint in groups:
        parent,label,current=groups[endpoint];previous=request.args.get('return_to','');parent_url=previous if previous.startswith(url_for('harness.'+parent)+'?') else url_for('harness.'+parent);return [(parent_url,_(label)),(None,_(current))]
    labels={'campaigns':'Campaigns','runs':'Runs','review':'Review','knowledge':'Knowledge','results':'Results','configuration':'Configuration','history':'History','sources':'Curated page sources'}
    return [(None,_(labels.get(endpoint,'Workspace')))]
