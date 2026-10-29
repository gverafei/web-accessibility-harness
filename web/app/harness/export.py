"""Offline review bundle: explicit allowlist, hashed records, fixtures and executable reanalysis."""
import hashlib
import io
import json
import zipfile
from pathlib import Path
from .contracts import canonical
from .providers import Ledger
from .reports import campaign_report

KINDS = {'campaign','contract_probe','evaluator_snapshot','sampling_frame','cohort_revision','page','capture','audit','run','run_result','decision','attempt','retention','technical_assessment',
         'retrieval',
         'execution_authorization','experience','policy','policy_validation','policy_promotion','policy_rollback','relevance_case',
         'relevance_rating','relevance_reference','acquisition_failure','capture_admission','call_receipt','call_reconciliation','execution_error','attempt_error','campaign_lifecycle','run_lifecycle','billing_reference','curated_source','replay_admission','learning_lineage','evidence_verification','category_review','taxonomy_assessment','taxonomy_supplement_evidence','taxonomy_judgment_cache','taxonomy_measurement_revision','retention_revision','source_fidelity_revision'}
SAFE_ROLES = {'candidate_html','network_html','rendered_html','capture_screenshot','captured_resource',
              'acquired_source_html','acquired_rendered_html','replay_source_html','axe_audit','lighthouse_audit','rendered_audit','screenshot_audit','taxonomy_supplement_audit','tranco_frame','curated_metadata','category_content','corrected_existing_paid_candidate'}
KINDS.add('selection_review_revision')
KINDS.add('local_refinement_decision')
KINDS.add('iteration_exclusion')
KINDS.add('iteration_accounting_revision')
KINDS.update(('source_repeatability', 'source_selection', 'acquisition_attempt',
              'acquisition_result', 'category_review_failure', 'acquisition_measurement',
              'acquisition_runtime_revision'))
SAFE_ROLES.update(('verified_dynamic_context_candidate', 'observed_mse_append',
                   'observed_worker_media_init'))
KINDS.update(('call_retry_authorization', 'campaign_execution_revision',
              'execution_recovery_result', 'provider_billing_reconciliation_basis',
              'provider_response_headers'))
PRIVATE_KINDS = {'sql_correction_archive','presentation_revision'}

def bundle(store, campaign, include_private_evidence=False):
    allowed_kinds=KINDS|PRIVATE_KINDS if include_private_evidence else KINDS
    manifest=store.get(campaign); rows=[manifest]+[r for r in store.list(campaign=campaign) if r['kind'] in allowed_kinds and r['id']!=campaign]
    # Reports match relevance collections by corpus and query digest across campaigns.
    from .contracts import digest
    queries={(r['data'].get('corpus_id'),digest(r['data']['query'])) for r in rows if r['kind']=='retrieval'}
    cases=[r for r in store.list('relevance_case') if (r['data']['corpus_id'],r['data'].get('query_digest')) in queries]
    case_ids={r['id'] for r in cases}
    rows += [r for r in cases if r['id'] not in {x['id'] for x in rows}]
    rows += [r for kind in ('relevance_rating','relevance_reference') for r in store.list(kind) if r['data']['case_id'] in case_ids and r['id'] not in {x['id'] for x in rows}]
    required={manifest['data']['corpus_id']} if manifest['data'].get('corpus_id') else set()
    required |= {r['data']['policy_id'] for r in rows if r['kind']=='run' and r['data'].get('policy_id')}
    for ident in required:
        if not any(r['id']==ident for r in rows): rows.append(store.get(ident))
    # Include only referenced ancestors (reused captures and learned versions), never unrelated campaigns.
    # Resolve only reachable references; loading every historical campaign
    # duplicates unrelated evidence and can exhaust export memory.
    known={}
    absent=set()
    def references(value):
        if isinstance(value,str):
            if value not in known and value not in absent:
                try:known[value]=store.get(value)
                except (KeyError, UnicodeEncodeError):absent.add(value)
            if value in known: yield value
        elif isinstance(value,dict):
            for child in value.values(): yield from references(child)
        elif isinstance(value,list):
            for child in value: yield from references(child)
    seen={r['id'] for r in rows};pending=list(rows)
    while pending:
        row=pending.pop()
        for ident in references(row['data']):
            ancestor=known[ident]
            if ident not in seen and ancestor['kind'] in allowed_kinds|{'artifact','corpus'}:
                seen.add(ident);rows.append(ancestor);pending.append(ancestor)
    referenced_artifacts=[r for r in rows if r['kind']=='artifact']
    rows=[r for r in rows if r['kind']!='artifact']
    import copy
    rows=copy.deepcopy(rows)
    if not include_private_evidence:
        for row in rows:
            if row['kind']=='review_case':
                for evidence in row['data']['evidence'].values():
                    if 'html' in evidence: evidence['html']='Private captured HTML excluded; see original artifact ID.'
                row['export_redaction']='Private page source removed; original record hash is retained as provenance.'
    from .reports import current_measurements
    _, consumption, _=current_measurements(store,campaign,store.list('run_result',campaign),Ledger(store).rows(campaign))
    files={'records.json':canonical(rows).encode(),'report.json':canonical(campaign_report(store,campaign)).encode(),
           'consumption.json':canonical([{k:v for k,v in c.items() if k not in ('request_id','response_id','error')} for c in consumption]).encode()}
    artifacts=[]; excluded=[]
    for row in {r['id']:r for r in store.list('artifact',campaign)+referenced_artifacts}.values():
        d=row['data']
        if d['role'] not in SAFE_ROLES or not (include_private_evidence or d['shareable']): excluded.append(row['id']); continue
        name='blobs/'+d['sha256']
        if name not in files:files[name]=store.read_blob(row['id'])
        artifacts.append(row)
    files['artifacts.json']=canonical(artifacts).encode()
    protocol=manifest['data'].get('protocol_bundle')
    if protocol:
        for document in protocol['documents']:
            files['protocol/'+document['name']]=document['content'].encode()
    for name in ('contracts.py','statistics.py','analysis.py','relevance.py','provenance.py','model_tasks.py'):
        # Offline reanalysis uses standard library metrics and supplied receipts, never HTTP dispatch.
        files['analysis/'+name]=Path(__file__).with_name(name).read_bytes()
    files['analysis/__init__.py']=b''
    files['reanalyze.py']=Path(__file__).with_name('reanalyze_template.py').read_bytes()
    files['plot.py']=Path(__file__).with_name('plot_template.py').read_bytes()
    files['fixture.json']=canonical({'provenance':'synthetic unit-test fixture, not an observation','pairs':[['passed','passed'],['passed','violated'],['violated','passed'],['violated','violated']],'expected_kappa':0}).encode()
    files['README.txt']=('Execution evidence. Run python reanalyze.py (standard library only).\n'
       'Reanalysis reproduces outcomes, PRE sensitivity, node changes and paired page-cluster intervals. Also reconstructs rag-reconstructed.json (precision, P@k, bounded recall@k, annotation coverage) and PROVENANCE.json. Original online decisions remain separate.\n'
       'Original records preserve initial and revised measurements and measured denominators. Optional python plot.py requires matplotlib and creates a 1000 dpi PNG plus editable SVG only for defined observed intervals.\n'
       'This archive contains no credentials or raw provider requests/responses. Corpus example licensing/provenance remain in records.json.\n'
       'Captured page evidence can contain personal/copyrighted material; inclusion is an explicit local export choice and requires review before redistribution.\n'
       'Excluded private evidence IDs: '+', '.join(excluded)+'\n').encode()
    hashes={name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
    files['MANIFEST.json']=canonical({'schema':'a11yharness/1','campaign_id':campaign,'manifest_hash':manifest['hash'],'files':hashes,
      'protocol_bundle':{'version':protocol['version'],'digest':protocol['digest']} if protocol else None,
      'included_private_evidence':include_private_evidence,'excluded_artifacts':excluded,'synthetic_fixture':'fixture.json'}).encode()
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,raw in sorted(files.items()): archive.writestr(name,raw)
    return stream.getvalue()
