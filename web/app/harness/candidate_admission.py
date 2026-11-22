"""Candidate-local observable checks; fidelity is a separately stored outcome."""
from urllib.parse import urljoin, urlsplit, unquote
from bs4 import BeautifulSoup
from .replay_admission import compare

VERSION='candidate-observable-admission-v5'


def endpoint(value,url):
    """Ground the endpoint, without pretending to verify remote query behavior."""
    try:
        target=urlsplit(urljoin(url,value))
        port=target.port
    except ValueError:return None
    if target.username is not None or target.password is not None:return None
    authority=target.hostname.lower()if target.hostname else target.netloc
    if port and port!={'https':443,'http':80}.get(target.scheme):authority+=':'+str(port)
    return target.scheme.lower(),authority,target.path or'/'


def check(source, visible, url, reference_source=None):
    scope='Visible content and decoded resources; declared fragment, form-owner and widget-target contracts. No remote navigation, backend submission or unobserved event-handler success is inferred.'
    if not isinstance(visible,dict):
        return {'version':VERSION,'status':'review_required','reasons':['missing_visible_evidence'],'metrics':{},'scope':scope}
    soup=BeautifulSoup(source,'html.parser'); reasons=[]; warnings=[]
    ids={n['id']for n in soup.select('[id]')}
    forms={n['id']for n in soup.select('form[id]')}
    if not str(visible.get('text','')).strip() and not visible.get('visible_images',0): reasons.append('blank_candidate')
    if visible.get('broken_images',0):reasons.append('broken_visible_resources')
    if visible.get('broken_media',0):reasons.append('broken_visible_media')
    broken_targets=[]
    base=urlsplit(url)
    for node in soup.select('a[href]'):
        try:target=urlsplit(urljoin(url,node['href']))
        except ValueError:
            broken_targets.append({'element':'a','target':node['href']});continue
        if target.fragment and (target.scheme,target.netloc,target.path,target.query)==(base.scheme,base.netloc,base.path,base.query) and unquote(target.fragment) not in ids:
            broken_targets.append({'element':'a','target':node['href']})
    for node in soup.select('input[form],button[form],select[form],textarea[form]'):
        if node['form'] not in forms:broken_targets.append({'element':node.name,'target':node['form']})
    for node in soup.select('[data-bs-target],a[data-bs-toggle][href]'):
        target=node.get('data-bs-target')or node.get('href')
        try:valid=bool(target and soup.select(target))
        except Exception:valid=False
        if not valid:broken_targets.append({'element':node.name,'target':target})
    if broken_targets:reasons.append('unresolved_local_control_target')
    invented_destinations=[]; invalid_destinations=[]
    if reference_source is not None:
        reference=BeautifulSoup(reference_source,'html.parser')
        verified={urljoin(url,n[attr])for n in reference.select('a[href],form[action],button[formaction],input[formaction]')for attr in ('href','action','formaction')if n.get(attr)}|{url}
        # Document alternates/canonical URLs are supplied source evidence too.
        # Stylesheet, prefetch and arbitrary script URLs are not navigation proof.
        verified.update(urljoin(url,n['href'])for n in reference.select('link[href]')
                        if {'alternate','canonical'}&set(n.get('rel',[]))
                        and not n.get('type','').lower().startswith(('text/css','image/')))
        # Explicit social page-identity metadata is a declared document URL,
        # like a canonical link, not an arbitrary URL found in a script/text.
        verified.update(urljoin(url,n['content'])for n in reference.select('meta[property="og:url"][content],meta[name="twitter:url"][content]'))
        supported={endpoint(value,url)for value in verified}-{None}
        query_changes=[]
        for node in soup.select('a[href],form[action],button[formaction],input[formaction]'):
            for attr in ('href','action','formaction'):
                if attr not in node.attrs:continue
                value=node[attr]
                try:target=urlsplit(urljoin(url,value))
                except ValueError:
                    invalid_destinations.append({'element':node.name,'attribute':attr,'target':value});continue
                local=target.fragment and (target.scheme,target.netloc,target.path,target.query)==(base.scheme,base.netloc,base.path,base.query)
                if endpoint(value,url)is None:
                    invalid_destinations.append({'element':node.name,'attribute':attr,'target':value});continue
                if not local and endpoint(value,url)not in supported:
                    invented_destinations.append({'element':node.name,'attribute':attr,'target':value})
                elif not local and urljoin(url,value)not in verified:
                    query_changes.append({'element':node.name,'attribute':attr,'target':value,'source_endpoints':[v for v in sorted(verified)if endpoint(v,url)==endpoint(value,url)],'scope':'Same source-supported endpoint; query/fragment differences recorded, remote behavior not assessed.'})
        # An absent source endpoint does not establish a broken destination.
        # Keep provenance available for grounded repair/human confirmation.
        if invented_destinations:warnings.append('destination_provenance_requires_human_confirmation')
        if invalid_destinations:reasons.append('invalid_candidate_destination')
    # A recorded script error is diagnostic evidence, not proof that all tasks
    # failed. The independent verifier sees this uncertainty explicitly.
    if visible.get('script_errors'):warnings.append('script_errors_require_agent_inspection')
    if soup.select('button[type=button],[onclick],[role=button]'):warnings.append('event_handler_task_success_not_assessed')
    return {'version':VERSION,'status':'rejected'if reasons else'admitted','reasons':reasons,
            'metrics':{'visible_images':visible.get('visible_images',0),'broken_images':visible.get('broken_images',0),
                       'broken_media':visible.get('broken_media',0),'unresolved_local_targets':broken_targets,'unverified_destinations':invented_destinations,'invalid_destinations':invalid_destinations,'destination_query_changes':query_changes if reference_source is not None else[]},
            'warnings':warnings,'scope':scope}


def evaluate(store, capture, audit, source, url, campaign, ident, reference_source=None):
    try:return store.get(ident)
    except KeyError:pass
    visible=audit['data'].get('raw_result',{}).get('transport',{}).get('visible')
    fidelity=compare(capture['data'].get('visible'),visible)
    reference_id=capture['data'].get('replay_source_id')or capture['data'].get('rendered_id')or capture['data'].get('source_id')
    if reference_source is None:reference_source=store.read_blob(reference_id).decode() if reference_id else None
    if reference_source is None:
        # The caller must bind reference bytes explicitly when capture metadata
        # uses another source field; never disable destination checks silently.
        return store.append('replay_admission',{'version':VERSION,'status':'review_required','reasons':['missing_reference_destination_evidence'],'metrics':{},'capture_id':capture['id'],'audit_id':audit['id'],'original':capture['data'].get('visible'),'replayed':visible,'source_fidelity':fidelity,'source_fidelity_enforced':False},campaign,ident)
    result=check(source,visible,url,reference_source)
    return store.append('replay_admission',result|{'capture_id':capture['id'],'audit_id':audit['id'],
        'original':capture['data'].get('visible'),'replayed':visible,'source_fidelity':fidelity,
        'source_fidelity_enforced':False},campaign,ident)
