"""Independent frozen-source repeat before inference; never average away drift."""
from urllib.parse import urlsplit
from bs4 import BeautifulSoup
from .contracts import digest

VERSION = 'frozen-source-repeatability-v2'


def restored_media_state(audit, document):
    """Normalize only a decoder-created URL proven by a restoration receipt.

    Original HTML and browser receipts remain byte-for-byte unchanged. Other
    blob URLs, changed layout/content and changed decoded media still differ.
    """
    data=audit['data'];diagnostics=data.get('replay',{}).get('diagnostics',{})
    restoration=diagnostics.get('mse_restoration',{})
    if (restoration.get('restoration_version')!='frozen-observed-mse-restoration-v2'
            or restoration.get('live_resources')is not False):return None
    soup=BeautifulSoup(document,'html.parser');media=[]
    for result in restoration.get('results',[]):
        old,new=result.get('original_src',''),result.get('current_src','')
        if result.get('status')!='restored' or not old.startswith('blob:') or not new.startswith('blob:'):return None
        if urlsplit(old[5:]).netloc!=urlsplit(new[5:]).netloc:return None
        try:nodes=soup.select(result['path'])
        except Exception:return None
        observed=[d for d in diagnostics.get('visible',{}).get('media_descriptors',[])
                  if d.get('position_path')==result['path']]
        if (len(nodes)!=1 or nodes[0].name not in ('video','audio')or nodes[0].get('src')!=new
                or len(observed)!=1 or observed[0].get('state')!='loaded' or observed[0].get('paused')is not True
                or observed[0].get('src_attribute')!=new or observed[0].get('current_src')!=new):return None
        nodes[0]['src']=old
        media.append({**observed[0],'src_attribute':old,'current_src':old})
    if not media:return None
    phase=diagnostics['phase_evidence']['phases'][0]
    return digest({'normalized_document':str(soup),'media':media,
                   'layout':phase.get('layout_sha256'),
                   'realm':{k:phase.get(k)for k in ('origin','url','viewport','scroll','version')}})


def compare(first, repeated, documents=None):
    reasons=[]
    fingerprints=[]
    for index,audit in enumerate((first, repeated)):
        data=audit.get('data', {})
        replay=data.get('replay', {})
        phases=replay.get('diagnostics', {}).get('phase_evidence', {})
        start=(phases.get('phases') or [{}])[0]
        fingerprint={key:replay.get(key)for key in
                     ('manifest_sha256','input_document_sha256','rendered_document_sha256')}
        fingerprint.update(state_sha256=start.get('sha256'),axe=data.get('axe'),
                           lighthouse=data.get('lighthouse'))
        if documents is not None:
            normalized=restored_media_state(audit,documents[index])
            if normalized is not None:fingerprint['state_sha256']=normalized
        if data.get('status')!='completed' or phases.get('stable')is not True:
            reasons.append('incomplete_repeat_measurement')
        if any(value is None for value in fingerprint.values()):
            reasons.append('missing_repeat_measurement_evidence')
        fingerprints.append(fingerprint)
    if not reasons and fingerprints[0]!=fingerprints[1]:
        reasons.append('source_measurement_not_repeatable')
    return {'version':VERSION,'status':'rejected'if reasons else'admitted',
            'reasons':list(dict.fromkeys(reasons)),'fingerprints':fingerprints,
            'audit_ids':[first.get('id'),repeated.get('id')],
            'scope':'Same input bytes, resource manifest, DOM/paint and audit values in independent browser documents. Decoder-created blob URLs are compared through exact validated restoration receipts and decoded media state; raw evidence remains unchanged. No provider calls.'}


def verify(store, environment, capture, source, baseline, campaign, config):
    ident='source-repeatability-'+digest({'capture_id':capture['id'],
          'audit_id':baseline['id'],'runtime':environment.runtime(),'version':VERSION})
    with store.named_lock(ident):
        return _verify_locked(store, environment, capture, source, baseline, campaign, config, ident)


def _verify_locked(store, environment, capture, source, baseline, campaign, config, ident):
    try:return store.get(ident)
    except KeyError:pass
    try:repeated=store.get(ident+'-audit')
    except KeyError:repeated=environment.audit(capture,source,campaign,ident+'-audit',config)
    documents=None
    if all(a.get('data',{}).get('artifacts',{}).get('rendered')for a in (baseline,repeated)):
        documents=[store.read_blob(a['data']['artifacts']['rendered']).decode()for a in (baseline,repeated)]
    return store.append('source_repeatability',compare(baseline,repeated,documents)|{
        'capture_id':capture['id'],'source_artifact_id':capture['data'].get('replay_source_id'),
        'paid_calls':0},campaign,ident)
