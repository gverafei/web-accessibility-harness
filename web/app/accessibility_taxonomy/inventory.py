"""Census of observable opportunities; never a detector for all catalogue types."""
import hashlib
import json
from collections import Counter
from urllib.parse import urljoin
from bs4 import BeautifulSoup, Comment
from . import RULES, summarize, EXCLUDED_TYPES, CURATION
from .selector_index import SelectorIndex

VERSION = 'observed-taxonomy-inventory-v11'
# Only these contextual questions have sufficient textual evidence in this
# instrument. Other observed opportunities explicitly abstain (no hidden tasks).
TEXTUAL = {'lang-mismatch', 'language-of-parts-mismatch',
           'page-title-not-descriptive', 'heading-not-descriptive',
           'landmark-purpose-mismatch', 'form-label-mismatch',
           'autocomplete-purpose-mismatch'}
SELECTORS = {
 'image-alt-not-descriptive': 'img[alt], svg[role=img], [role=img], object',
 'video-captions-inaccurate': 'video', 'lang-mismatch': 'html[lang]',
 'language-of-parts-mismatch': '[lang]:not(html)',
 'link-text-mismatch': 'a[href]', 'button-label-mismatch': 'button, [role=button]',
 'form-label-mismatch': 'input:not([type=hidden]), select, textarea',
 'widget-label-purpose-mismatch': '[role=tab], [role=menuitem], [role=treeitem], [role=option], [role=switch]',
 'heading-not-descriptive': 'h1,h2,h3,h4,h5,h6,[role=heading]',
 'landmark-purpose-mismatch': 'main,nav,aside,header,footer,[role=search],[role=region]',
 'page-title-not-descriptive': 'title', 'autocomplete-purpose-mismatch': 'input[autocomplete]',
 'aria-state-mismatch': '[aria-expanded],[aria-selected],[aria-checked],[aria-pressed]',
 'table-header-association-mismatch': 'td[headers],th[scope]',
 'error-message-mismatch': '[aria-errormessage]'}

def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()

def language_text(node):
    """Text governed by this declaration, excluding nested language overrides.

    A multilingual parent's combined text is not evidence of a mismatch in
    each correctly declared passage. Scripts/styles are not readable content.
    """
    parts=[]
    for text in node.find_all(string=True):
        if isinstance(text,Comment):continue
        parent=text.parent
        excluded=False
        while parent is not None:
            if parent.name in ('script','style','template','noscript'):
                excluded=True;break
            if parent is node:break
            if parent.get('lang'):
                excluded=True;break
            parent=parent.parent
        if not excluded and text.strip():parts.append(text.strip())
    return ' '.join(parts)

def inventory(html, axe, origin, observations=None):
    from .semantic_context import RELATIONAL,context as purpose_context
    if observations and observations.get("document_sha256")!=sha(html):
        raise ValueError("Semantic observations must match exact document")
    soup = BeautifulSoup(html, 'html.parser')
    selector_index=SelectorIndex(soup)
    document_hash = sha(html)
    nodes = list(soup.find_all(True))
    ids = Counter(n.get('id') for n in nodes if n.get('id'))
    positions={id(node):index for index,node in enumerate(nodes)}
    text_keys={id(n):n.name+':'+str(n.get('role',''))+':'+n.get_text(' ',strip=True) for n in nodes}
    text_counts=Counter(text_keys.values())
    resource_keys={}
    for n in nodes:
        for attr in ('src','href','name'):
            if n.get(attr):
                value=urljoin(origin,n[attr]) if attr in ('src','href') else n[attr]
                resource_keys[(id(n),attr)]=n.name+':'+attr+':'+value
    resource_counts=Counter(resource_keys.values())
    def identity(node):
        if node.get('id') and ids[node['id']]==1: return 'id:'+node['id']
        for attr in ('src','href','name'):
            key=resource_keys.get((id(node),attr))
            if key and resource_counts[key]==1: return key
        key=text_keys[id(node)]
        if text_counts[key]==1: return key
        return 'ambiguous:'+document_hash+':'+str(positions[id(node)])
    rows={}; observed_types=set(); warnings=[]
    for group,status in (('passes','passed'),('violations','failed'),('incomplete','insufficient_evidence')):
        for rule in axe.get(group,[]):
            typ=rule.get('id')
            if typ in EXCLUDED_TYPES:continue
            if not typ or RULES.get(typ,{}).get('category')=='Semantic': continue
            if not any(str(t).startswith('wcag') for t in rule.get('tags',[])): continue
            observed_types.add(typ)
            for item in rule.get('nodes',[]):
                target=item.get('target',[])
                try: matched=selector_index.select(target[0]) if len(target)==1 and isinstance(target[0],str) else []
                except Exception: matched=[]
                key=identity(matched[0]) if len(matched)==1 else 'unmatched:'+document_hash+':'+json.dumps(target,sort_keys=True)
                ident=sha(typ+':'+key)
                row={'opportunity_id':ident,'type':typ,'status':status,
                     'impact':item.get('impact') or rule.get('impact') or RULES.get(typ,{}).get('impact'),
                     'identity_basis':key,'method':'axe','target':target}
                if ident in rows and rows[ident]['status']!=status:
                    row['status']='error';warnings.append('Conflicting Axe verdicts: '+ident)
                rows[ident]=row
    # A deliberately narrow applicability case for WCAG 2.4.1: a simple
    # paragraph document with at most one link contains no bypassable block.
    # W3C excludes individual links from blocks; arbitrary wrappers, navigation,
    # forms/frames or other structures remain inconclusive, never guessed away.
    simple_body=soup.body
    if simple_body:
        children=[n for n in simple_body.find_all(recursive=False) if n.name not in ('script','style','svg')]
        plain=bool(children) and all(n.name in ('p','a') for n in children)
        links=simple_body.select('a[href]')
        controls=simple_body.select('button,input,select,textarea,iframe,object,nav,header,footer,[role]')
        paragraph_controls=any(n.select('a,button,input,select,textarea,iframe,object,[role]') for n in children if n.name=='p')
        if plain and len(links)<=1 and not controls and not paragraph_controls:
            for row in rows.values():
                if row['type']=='bypass' and row['status']=='insufficient_evidence':
                    row.update(status='not_applicable',method='snapshot_bypass_applicability',
                        supplementary_evidence={'version':'simple-document-bypass-v1','document_sha256':document_hash,
                            'criterion':'WCAG2.4.1','link_count':len(links),
                            'reason':'Simple observed paragraph document with no navigation or repeated control block; an individual link is not a block.',
                            'source':'https://www.w3.org/WAI/WCAG22/Understanding/bypass-blocks.html',
                            'scope':'Applicability to this frozen snapshot only, not a site-wide conformance judgment.'})
    # Page purpose is established by body content, not by echoing its title.
    body=soup.body or soup
    page_text=' '.join(str(t).strip() for t in body.find_all(string=True)
                       if not isinstance(t,Comment) and str(t).strip() and
                       not any(p.name in ('script','style','template','noscript','head') for p in t.parents))
    for typ,selector in SELECTORS.items():
        if typ in EXCLUDED_TYPES:continue
        for node in soup.select(selector):
            observed_types.add(typ); key=identity(node); ident=sha(typ+':'+key)
            local=node.parent if node.parent and node.name not in ('html','title') else soup
            labels=[label.get_text(' ',strip=True) for label in soup.select('label') if node.get('id') and label.get('for')==node['id']]
            labelled=[soup.find(id=ident) for ident in str(node.get('aria-labelledby','')).split()]
            labels.extend(label.get_text(' ',strip=True) for label in labelled if label)
            context={'element':{'tag':node.name,'attributes':dict(node.attrs),'text':node.get_text(' ',strip=True) if node.name!='html' else None,'labels':labels}, 'observed_text':local.get_text(' ',strip=True),
                     'page_title':soup.title.get_text(' ',strip=True) if soup.title else '',
                     'page_language':soup.html.get('lang') if soup.html else None}
            if typ in RELATIONAL:
                context['observed_purpose']=purpose_context(typ,node,soup,origin,observations)
            if typ=='image-alt-not-descriptive':
                link=node.find_parent('a')
                context['image_usage']={'container_html':str(local),
                    'link_html':str(link) if link else None,
                    'link_text':link.get_text(' ',strip=True) if link else None,
                    'link_href':urljoin(origin,link.get('href','')) if link else None,
                    'role':node.get('role'), 'aria_hidden':node.get('aria-hidden')}
            if typ=='heading-not-descriptive':
                section=node.parent
                # Linked headings and isolated wrappers need their containing
                # group, not just their own repeated label. Still no navigation.
                for _ in range(2):
                    if section and section.parent and section.get_text(' ',strip=True)==node.get_text(' ',strip=True):
                        section=section.parent
                    else:break
                context['section_html']=str(section) if section else ''
                context['observed_text']=section.get_text(' ',strip=True) if section else ''
                context['content_scope']='Complete containing heading group; linked headings describe supplied navigation markup, not unvisited destination contents.'
            if typ=='landmark-purpose-mismatch':
                context['region_html']=str(node)
                context['content_scope']='Complete supplied region markup and text; judge region purpose, not destinations or interaction success.'
            if typ in ('lang-mismatch','page-title-not-descriptive'): context['observed_text']=page_text
            if typ=='page-title-not-descriptive':
                context['content_scope']='Complete text of the supplied document body, excluding title, scripts and non-readable metadata. No truncated sample.'
            if typ in ('lang-mismatch','language-of-parts-mismatch'):
                scoped=language_text(node)
                context['element']['text']=scoped
                context['observed_text']=scoped
                context['language_scope']='Only text governed by this element; nested explicit lang declarations excluded.'
                context['declared_language']=node.get('lang')
                context.pop('page_language',None)
            complete=len(json.dumps(context,ensure_ascii=False).encode())<=24000
            rows[ident]={'opportunity_id':ident,'type':typ,'status':'insufficient_evidence',
                'identity_basis':key,'method':'decisions' if typ in TEXTUAL|RELATIONAL and complete else 'unobserved_supplement',
                'context':context if complete else {'reason':'Complete contextual evidence exceeds instrument bound'},
                'impact':RULES[typ].get('impact')}
    opportunities=sorted(rows.values(),key=lambda r:r['opportunity_id'])
    return {'version':VERSION,'curation_version':CURATION['version'],'excluded_types':CURATION['excluded_types'],'document_sha256':document_hash,'origin':origin,
            'opportunities':opportunities,'summary':summarize(opportunities),'warnings':warnings,'unmapped_axe_rules':sorted(observed_types-set(RULES)),
            'type_coverage':{typ:('observed_axe' if RULES[typ]['category']!='Semantic' else
                                 'textual_context' if typ in TEXTUAL|RELATIONAL else 'supplement_unobserved')
                             if typ in observed_types else 'not_observed_or_not_implemented' for typ in RULES},
            'scope':'WCAG-tagged Axe observations and declared contextual census; no task, zoom, video or expert-equivalence claim.'}

def sidecar_path(source_path):
    from pathlib import Path
    if not source_path: return None
    path=Path(source_path).resolve()
    return path.with_suffix('.taxonomy.json') if path.is_relative_to(Path('/results').resolve()) else None

def acquired_inventory(item):
    """Persist an unpaid acquisition census beside its immutable raw artifacts."""
    from pathlib import Path
    source=item.get('source_snapshot_path'); axe_path=item.get('axe',{}).get('raw_path')
    target=sidecar_path(source)
    if not target or not axe_path: return None
    axe_file=Path(axe_path).resolve()
    if not axe_file.is_relative_to(Path('/results').resolve()): return None
    if not Path(source).is_file() or not axe_file.is_file(): return None
    record=inventory(Path(source).read_text(),json.loads(axe_file.read_text()),
        item.get('acquisition',{}).get('captured_url') or item.get('url'))
    raw=json.dumps(record,ensure_ascii=False,sort_keys=True)
    if target.exists() and target.read_text()!=raw:
        raise ValueError('Acquisition taxonomy evidence is immutable')
    target.write_text(raw)
    return record

def read_acquired(source_path):
    path=sidecar_path(source_path)
    return json.loads(path.read_text()) if path and path.is_file() else None
