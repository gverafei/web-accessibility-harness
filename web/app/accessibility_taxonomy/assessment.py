"""Document-bound measurement; judges remain blinded to policy and worker.

Historical methods measure the retained outcome. The current improvement-based
controller also requests candidate measurements before its deterministic choice.
"""
import json
import base64
import hashlib
from urllib.parse import urljoin
from . import contextual_review, summarize, compare, CURATION
from .inventory import inventory
from harness.contracts import digest, ContractError
from harness.providers import BudgetStop, UncertainCall

VERSION = 'retained-taxonomy-assessment-v18'

BATCH_POLICY = 'grouped-evidence-modality-v2'
from .image_review import IDENTITY_TRANSPORT


def review_batches(opportunities, images):
    """Keep whole cases, grouping modalities instead of flushing on every alternation."""
    text = [row for row in opportunities if row['opportunity_id'] not in images]
    visual = [row for row in opportunities if row['opportunity_id'] in images]
    return [group[i:i+size] for group,size in ((text,20),(visual,4))
            for i in range(0,len(group),size)]


def _assess_base(store, providers, run, audit, origin, model, capture=None):
    artifacts=audit['data'].get('artifacts',{})
    if audit['data'].get('status')!='completed' or not all(artifacts.get(k) for k in ('rendered','axe')):
        raise ContractError('Taxonomy needs completed same-document HTML and Axe evidence')
    html=store.read_blob(artifacts['rendered']).decode()
    raw=json.loads(store.read_blob(artifacts['axe']))
    supp=artifacts.get('taxonomy_supplement')
    observed=json.loads(store.read_blob(supp)).get('semantic_observations') if supp else None
    record=inventory(html,raw,origin,observed)
    images={}
    projected_assets={}
    assets={a['url']:a for a in (capture or {}).get('data',{}).get('assets',[])}
    for row in record['opportunities']:
        element=row.get('context',{}).get('element',{})
        if row['type']!='image-alt-not-descriptive' or element.get('tag')!='img': continue
        attrs=element.get('attributes',{}); source=urljoin(origin,attrs.get('src',''))
        asset=assets.get(source)
        if not asset or not model or not model.get('vision'): continue
        mime=asset['mime'].split(';')[0].strip()
        if mime not in ('image/png','image/jpeg','image/webp'): continue
        body=store.read_blob(asset['artifact_id'])
        if hashlib.sha256(body).hexdigest()!=asset['sha256']:
            raise ContractError('Taxonomy supplementary image hash mismatch')
        row['method']='decisions'
        row['context']['supplementary_image']={'url':source,'sha256':asset['sha256']}
        from .image_projection import image_part
        if asset['sha256'] not in projected_assets:
            projected_assets[asset['sha256']] = image_part(body, mime)
        part, projection = projected_assets[asset['sha256']]
        images[row['opportunity_id']] = part
        if projection:
            row['context']['supplementary_image']['projection'] = projection
    from .contextual_judge import protocol
    judge_protocol = protocol(model)
    contract = {'version':VERSION,'batch_policy':BATCH_POLICY,'image_identity_transport':IDENTITY_TRANSPORT,'inventory':record,'model':model}
    if judge_protocol:
        contract['judge_protocol'] = judge_protocol
    fingerprint=digest(contract)
    ident='taxonomy-document-'+fingerprint
    with store.named_lock(ident):
        return _complete_assessment(store, providers, run, audit, origin, record, images, model, fingerprint, ident)


def _complete_assessment(store, providers, run, audit, origin, record, images, model, fingerprint, ident):
    from .checkpoints import assessment_checkpoint, save_assessment
    saved, receipt_id, parent = assessment_checkpoint(store, providers, ident)
    if saved is not None: return saved
    opportunities=record['opportunities']; eligible=[r for r in opportunities if r['method']=='decisions']
    answers=[]; errors=[]
    # A census, not a silently truncated first-N sample. Each batch remains
    # complete; rejected budget/context leaves the remainder visibly unassessed.
    batches=review_batches(eligible,images)
    progress_id=run+'-taxonomy-progress'
    completed=0
    store.checkpoint(progress_id,{'stage':'contextual','audit_id':audit['id'],'status':'running','completed':0,'total':len(eligible)})
    for index,batch in enumerate(batches):
        image_rows=[r for r in batch if r['opportunity_id'] in images]
        parts=[images[r['opportunity_id']] for r in image_rows]
        try:
            if image_rows:
                from .image_review import review
                judged=review(store,providers,run,ident+'-batch-'+str(index),batch,parts)
            else:
                judged=contextual_review(store,providers,run,ident+'-batch-'+str(index),model,
                    {'instrument':VERSION,'origin':origin,'document_sha256':record['document_sha256'],
                     'scope':record['scope']},batch)
            resolved={r['opportunity_id']:r for r in judged['data']['opportunities']}
            opportunities=[resolved.get(r['opportunity_id'],r) for r in opportunities]
            answers.append(judged['id'])
            completed+=len(batch)
            store.checkpoint(progress_id,{'stage':'contextual','audit_id':audit['id'],'status':'running','completed':completed,'total':len(eligible)})
        except UncertainCall:
            # Never continue with unresolved provider consumption.
            raise
        except (BudgetStop,ContractError,ValueError,KeyError) as error:
            errors.append(str(error));break
    store.checkpoint(progress_id,{'stage':'contextual','audit_id':audit['id'],'status':'interrupted'if errors else'completed','completed':completed,'total':len(eligible)})
    calls=providers.ledger.rows()
    # Batch receipt keys are bound to the document fingerprint, independent of
    # worker/level identity; shared baselines refer to the original paid receipt.
    own=[c for c in calls if str(c.get('logical_key','')).startswith(ident)]
    from .contextual_judge import protocol
    return save_assessment(store, providers, receipt_id, parent, {'version':VERSION,'batch_policy':BATCH_POLICY,'image_identity_transport':IDENTITY_TRANSPORT,'fingerprint':fingerprint,
        'audit_id':audit['id'],'document_sha256':record['document_sha256'],'model':model,
        'opportunities':opportunities,'summary':summarize(opportunities),
        'type_coverage':record['type_coverage'],'scope':record['scope'],
        'judgment_ids':answers,'errors':errors,'call_ids':[c['id'] for c in own],
        'measurement_cost_usd':sum(c['cost'] or 0 for c in own),
        **({'judge_protocol':protocol(model)} if protocol(model) else {})})

def assess(store, providers, run, audit, origin, model, capture=None):
    from .contextual_judge import resolve
    model = resolve(providers, model)
    base=_assess_base(store,providers,run,audit,origin,model,capture)
    artifact=audit['data'].get('artifacts',{}).get('taxonomy_supplement')
    if not artifact:return base
    from .supplement import resolve
    return resolve(store,providers,run,base,json.loads(store.read_blob(artifact)),model)

def coverage(opportunities):
    from collections import Counter
    pending=[r for r in opportunities if r['status'] in ('insufficient_evidence','error')]
    outside=[r for r in pending if r.get('method')=='unobserved_supplement']
    return {'outside_scope':len(outside),'inconclusive':len(pending)-len(outside),
            'outside_types':dict(Counter(r['type'] for r in outside)),
            'inconclusive_types':dict(Counter(r['type'] for r in pending if r not in outside))}


def outcome(original, retained):
    return {'version':VERSION,'curation_version':CURATION['version'],'excluded_types':CURATION['excluded_types'],'supplementary_evidence_ids':[a['data']['supplement_artifact_id'] for a in (original,retained) if a['data'].get('supplement_artifact_id')],'supplement_version':retained['data'].get('supplement_version') or original['data'].get('supplement_version'),'coverage_detail':{'original':coverage(original['data']['opportunities']),'retained':coverage(retained['data']['opportunities'])},'original_assessment_id':original['id'],
        'retained_assessment_id':retained['id'],
        'comparison':compare(original['data']['opportunities'],retained['data']['opportunities']),
        'original':original['data']['summary'],'retained':retained['data']['summary'],
        'errors':original['data']['errors']+retained['data']['errors']}


def measure_pair(store, providers, run, baseline, retained, origin, model, capture=None):
    from contextlib import nullcontext
    stage = providers.complete_stage('taxonomy', run) if callable(getattr(type(providers), 'complete_stage', None)) else nullcontext()
    with stage:
        return _measure_pair(store, providers, run, baseline, retained, origin, model, capture)


def _measure_pair(store, providers, run, baseline, retained, origin, model, capture=None):
    try:
        original=assess(store,providers,run,baseline,origin,model,capture)
        final=original if baseline['id']==retained['id'] else assess(store,providers,run,retained,origin,model,capture)
        result=outcome(original,final)
        result['measurement_cost_usd']=original['data']['measurement_cost_usd']+(0 if final['id']==original['id'] else final['data']['measurement_cost_usd'])
        result['shared_baseline_cost_usd']=original['data']['measurement_cost_usd']
        result['status']='completed' if not result['errors'] else 'partial'
        return result
    except UncertainCall:
        raise
    except (BudgetStop,ContractError,ValueError,KeyError) as error:
        return {'version':VERSION,'status':'not_assessed','errors':[str(error)],
                'baseline_audit_id':baseline['id'],'retained_audit_id':retained['id']}
