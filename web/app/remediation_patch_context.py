"""Focused current-document evidence shared by SQL and native repair paths."""
import json
import re
from bs4 import BeautifulSoup

VERSION = "focused-patch-context-v4"

def exact_selector(soup, node):
    """Derive one verifiable path, including when authored IDs are duplicated."""
    parts = []
    current = node
    while current and current.name != '[document]':
        identity = current.get('id')
        if identity and len(soup.find_all(id=identity)) == 1:
            parts.insert(0, '[id=' + json.dumps(identity, ensure_ascii=False) + ']')
            break
        siblings = current.parent.find_all(current.name, recursive=False)
        position = next(i for i, sibling in enumerate(siblings, 1) if sibling is current)
        parts.insert(0, current.name + ':nth-of-type(' + str(position) + ')')
        current = current.parent
    selector = ' > '.join(parts)
    try:
        matches = soup.select(selector)
    except Exception:
        return None
    if len(matches) != 1 or matches[0] is not node:
        return None
    return selector


def interactive_descendants(soup, node, attributes):
    controls = node.select('a,button,input,select,textarea,summary,[tabindex],[role],[contenteditable]')
    evidence = []
    for child in controls[:16]:
        selector = exact_selector(soup, child)
        if selector:
            evidence.append({'selector': selector, 'match_count': 1, 'element': child.name,
                             **attributes(child), 'text': child.get_text(' ', strip=True)[:120]})
    return {'interactive_descendants': evidence,
            'interactive_descendants_omitted': max(0, len(controls) - 16)}

def contextual_targets(soup, evidence):
    """Locate measured elements uniquely in the current source; never guess a selector."""
    targets, unresolved = [], []
    for finding in (evidence or {}).get('failed_opportunities', []):
        element = (finding.get('context') or {}).get('element') or {}
        tag, attrs, text = element.get('tag'), element.get('attributes'), element.get('text')
        if (not isinstance(tag, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', tag)
                or not isinstance(attrs, dict) or not isinstance(text, str)):
            unresolved.append({'type':finding.get('type'), 'status':'element_identity_unavailable'})
            continue
        matches = [node for node in soup.find_all(tag)
                   if all(node.get(key) == value for key, value in attrs.items())
                   and ' '.join(node.get_text(' ', strip=True).split()) == ' '.join(text.split())]
        selector = exact_selector(soup, matches[0]) if len(matches) == 1 else None
        if selector:
            targets.append(selector)
        else:
            unresolved.append({'type':finding.get('type'), 'status':'ambiguous_or_unmatched_element',
                               'match_count':len(matches)})
    return list(dict.fromkeys(targets)), unresolved


def repair_context(source, axe_evidence, lighthouse_evidence, limit=50000, *, contextual_evidence=None, target_coverage=None):
    """Give patch targets their actual relationships and explicit partial scope."""
    if target_coverage is not None:
        from grounded_patch_context import SUPPORTED_VERSIONS, repair_context as grounded_context
        if target_coverage not in SUPPORTED_VERSIONS:
            raise ValueError('Unknown target coverage contract')
        return grounded_context(source, axe_evidence, lighthouse_evidence, limit,
                                contextual_evidence=contextual_evidence, version=target_coverage)
    from harness.html_tools import compact_html
    soup=BeautifulSoup(source,"html.parser")
    def excerpt(node, allowance):
        value=str(node or '')
        return {'html':value[:allowance],'html_length':len(value),'html_truncated':len(value)>allowance}
    def attributes(node):
        values={}; abbreviated=[]
        for key,value in (node.attrs if node else {}).items():
            # A huge inline payload is context, never permission to rewrite it.
            if isinstance(value,str) and len(value)>2000:
                values[key]=value[:2000];abbreviated.append(key)
            else:values[key]=value
        return {'attributes':values,'attributes_abbreviated':abbreviated}
    head_evidence=excerpt(soup.head,18000)
    head=head_evidence['html']
    nodes=[]
    selectors=[]
    unresolved_targets=[]
    def add_target(target, instrument):
        if isinstance(target, str) and target:
            selectors.append(target)
        elif isinstance(target, list) and len(target) == 1 and isinstance(target[0], str):
            selectors.append(target[0])
        elif target:
            unresolved_targets.append({'target': target, 'instrument': instrument,
                'status': 'nested_or_unsupported_context',
                'scope': 'Not a top-level CSS selector; retain the original browser path.'})
    for violation in axe_evidence or []:
        for node in violation.get('nodes') or []:
            add_target(node.get('target'), 'Axe')
    for audit in lighthouse_evidence or []:
        for item in audit.get('items') or []:
            add_target(item.get('selector'), 'Lighthouse')
    contextual, unresolved_contextual = contextual_targets(soup, contextual_evidence)
    for selector in contextual:
        add_target(selector, 'Contextual taxonomy')
    selectors=list(dict.fromkeys(selectors))
    unresolved_targets=list({json.dumps(item,sort_keys=True):item for item in unresolved_targets}.values())
    selector_evidence=[]
    for selector in selectors[:24]:
        try: matches=soup.select(selector); selector_status='matched' if matches else 'no_match'
        except Exception: matches=[];selector_status='invalid_selector'
        selector_evidence.append({'selector':selector,'status':selector_status,'match_count':len(matches),
                                  'instances_omitted':max(0,len(matches)-2)})
        for position,match in enumerate(matches[:2],1):
            parent=match.parent
            previous=excerpt(match.find_previous_sibling(),600);following=excerpt(match.find_next_sibling(),600)
            related=[]
            for relation in ('aria-labelledby','aria-describedby','aria-controls','headers'):
                for identity in (match.get(relation)or'').split():
                    references=soup.find_all(id=identity)
                    related.append({'relation':relation,'id':identity,'match_count':len(references),
                                    'elements':[excerpt(ref,1600)for ref in references]})
            if match.get('id'):
                related.extend({'relation':'label-for','id':match['id'],**excerpt(label,1600)}
                               for label in soup.find_all('label',attrs={'for':match['id']}))
            label=match.find_parent('label')
            if label:related.append({'relation':'enclosing-label',**excerpt(label,1600)})
            fieldset=match.find_parent('fieldset')
            if fieldset and fieldset.find('legend',recursive=False):
                related.append({'relation':'fieldset-legend',**excerpt(fieldset.find('legend',recursive=False),1600)})
            form=match.find_parent('form')
            ancestors=[{'element':ancestor.name,**attributes(ancestor)}for ancestor in list(match.parents)[:6]]
            children=parent.find_all(recursive=False)
            nodes.append({'selector':selector,'match_index':position,'match_count':len(matches),
                          **excerpt(match,2500),**attributes(match),'related_elements':related,
                          **interactive_descendants(soup, match, attributes),
                          'enclosing_form':attributes(form)if form else None,'ancestors':ancestors,
                          'parent':{'element':parent.name,'id':parent.get('id'),'classes':parent.get('class',[]),
                                    'child_elements':[child.name for child in children][:40],
                                    'child_elements_omitted':max(0,len(children)-40)},
                          'previous_sibling':previous['html'],'previous_sibling_truncated':previous['html_truncated'],
                          'next_sibling':following['html'],'next_sibling_truncated':following['html_truncated']})
    containers=[]
    for node in soup.select('main,article,section,body > div,body > header,body > footer,div[id]'):
        text=node.get_text(' ',strip=True)
        if not text and not node.select('img,iframe,video,input,button'): continue
        identity=node.get('id')
        if identity and len(soup.find_all(id=identity))==1:
            selector='[id='+json.dumps(identity)+']'
        else:
            classes=node.get('class',[])
            selector=node.name+''.join('.'+value for value in classes if re.match(r'^[a-zA-Z_][\w-]*$',value))
            if selector==node.name or len(soup.select(selector))!=1: continue
        containers.append({'selector':selector,'element':node.name,'role':node.get('role'),
                           'words':len(text.split()),'text_start':text[:160],
                           'images':len(node.select('img')),'iframes':len(node.select('iframe')),
                           'controls':len(node.select('input,button,select,textarea'))})
    overview=compact_html(source,len(source)+1)
    payload={'version':VERSION,'scope':'Static current source evidence, not browser task verification',
             "document_head":head,'document_head_length':head_evidence['html_length'],
             'document_head_truncated':head_evidence['html_truncated'],"affected_nodes":nodes,"document_size":len(source),
             'selector_evidence':selector_evidence, 'unresolved_targets':unresolved_targets[:24],
             'unresolved_targets_omitted':max(0,len(unresolved_targets)-24),'selectors_omitted':max(0,len(selectors)-24),
             "substantive_container_candidates":containers[:40],
             'container_candidates_omitted':max(0,len(containers)-40),
             "independent_page_overview":overview[:18000],
             'independent_page_overview_truncated':len(overview)>18000,
             'overview_transformations':'Comments, inline scripts/styles/noscript and SVG interiors omitted; not a complete replacement source.'}
    if contextual_evidence is not None:
        payload.update(version='focused-patch-context-v5', contextual_target_selectors=contextual,
                       unresolved_contextual_targets=unresolved_contextual)
    # Bound context without cutting a JSON string mid-object. Explicitly report
    # omitted context; execution still patches the full frozen document.
    payload['context_nodes_omitted']=0
    payload['selector_evidence_omitted']=0
    if len(json.dumps(payload,ensure_ascii=False))>limit:
        payload['independent_page_overview']='Omitted to prioritize measured targets and their control relationships.'
        payload['independent_page_overview_truncated']=True
    while len(json.dumps(payload,ensure_ascii=False))>limit and payload['affected_nodes']:
        payload['affected_nodes'].pop(); payload['context_nodes_omitted']+=1
    if len(json.dumps(payload,ensure_ascii=False))>limit:
        payload['independent_page_overview']='Context allowance exceeded; focused nodes unavailable'
        payload['independent_page_overview_truncated']=True
        payload['document_head']=head[:max(0,limit//2)]
        payload['document_head_truncated']=len(payload['document_head'])<head_evidence['html_length']
        while len(json.dumps(payload,ensure_ascii=False))>limit and payload['substantive_container_candidates']:
            payload['substantive_container_candidates'].pop();payload['container_candidates_omitted']+=1
        while len(json.dumps(payload,ensure_ascii=False))>limit and payload['selector_evidence']:
            payload['selector_evidence'].pop();payload['selector_evidence_omitted']+=1
    while len(json.dumps(payload,ensure_ascii=False))>limit and payload['unresolved_targets']:
        payload['unresolved_targets'].pop();payload['unresolved_targets_omitted']+=1
    return json.dumps(payload,ensure_ascii=False)
