"""Observed purpose/relationships; no navigation, interaction or invented tasks."""
from urllib.parse import urljoin,urlsplit

VERSION='observed-semantic-context-v3'
RELATIONAL={'link-text-mismatch','button-label-mismatch','widget-label-purpose-mismatch',
            'aria-state-mismatch','table-header-association-mismatch','error-message-mismatch'}

def names(node,soup):
    refs=[soup.find(id=x) for x in str(node.get('aria-labelledby','')).split()]
    if refs and all(x is not None for x in refs):return ' '.join(x.get_text(' ',strip=True) for x in refs)
    if node.get('aria-label'):return node['aria-label']
    clone=type(soup)(str(node),'html.parser')
    for image in clone.select('img[alt]'):image.replace_with(image['alt'])
    for el in clone.select('script,style,template,[aria-hidden=true]'):el.decompose()
    return clone.get_text(' ',strip=True) or node.get('title','')

def selector(node):
    pieces=[]
    while node and getattr(node,'name',None) and node.name!='[document]':
        position=1+len(node.find_previous_siblings(node.name))
        pieces.append(node.name+':nth-of-type('+str(position)+')');node=node.parent
    return ' > '.join(reversed(pieces))

def context(typ,node,soup,origin,observations=None):
    data={'version':VERSION,'accessible_name':names(node,soup),
          'element_html':str(node),'evidence_scope':'Observed page/configured purpose and relationships only; no destination visit, click, successful task or remote content verification.'}
    refs={}
    for attr in ('aria-controls','aria-describedby','aria-errormessage'):
        refs[attr]=[{'id':x,'html':str(soup.find(id=x)) if soup.find(id=x) else None} for x in str(node.get(attr,'')).split()]
    data['references']=refs
    parent=node.find_parent(['p','li','td','th']) or node.parent
    if typ=='link-text-mismatch' and parent and parent.name in ('h1','h2','h3','h4','h5','h6') and parent.parent:
        parent=parent.parent
    data['programmatic_context_html']=str(parent) if parent else ''
    if typ=='link-text-mismatch':
        target=urljoin(origin,node.get('href',''));data['configured_destination']=target
        parts=urlsplit(target);here=urlsplit(origin)
        fragment=soup.find(id=parts.fragment) if parts.fragment and (parts.scheme,parts.netloc,parts.path,parts.query)==(here.scheme,here.netloc,here.path,here.query) else None
        data['same_document_target_html']=str(fragment) if fragment else None
        data['destination_visited']=False
    if typ in ('button-label-mismatch','widget-label-purpose-mismatch'):
        form=soup.find(id=node.get('form')) if node.get('form') else node.find_parent('form')
        data['form_html']=str(form) if form else None
        data['configured_action']={'type':node.get('type','submit' if node.name=='button' and form else None),
            'formaction':node.get('formaction') or (form.get('action') if form else None),
            'target':node.get('popovertarget'),'onclick':node.get('onclick'), 'title':node.get('title')}
    if typ=='table-header-association-mismatch':
        table=node.find_parent('table');data['table_html']=str(table) if table else None
        data['header_references']=[{'id':x,'html':str(soup.find(id=x)) if soup.find(id=x) else None} for x in node.get('headers',[])]
    if typ=='error-message-mismatch':
        data['constraints']={k:node.get(k) for k in ('type','required','pattern','min','max','minlength','maxlength','placeholder','name') if node.has_attr(k)}
        labels=soup.select('label');data['field_labels']=[x.get_text(' ',strip=True) for x in labels if node.get('id') and x.get('for')==node['id']]
    if observations:
        matches=[x for x in observations.get('elements',[]) if x.get('selector')==selector(node)]
        if len(matches)==1:data['rendered_observation']=matches[0]
    return data

RUBRICS={
'link-text-mismatch': 'Judge whether the accessible name plus programmatic context conveys an identifiable configured purpose. A named application/document, platform, language switch, article or download in relevant context is sufficient; do not require visiting a remote page. A generic name such as Click here is failed ONLY when its programmatic context does not identify purpose and a specific purpose is otherwise observable. A clearly contradictory name versus a same-document target or independently established configured purpose is failed. A remote URL slug alone is not proof that a descriptive umbrella category is wrong: About can label a supplied group of FAQ, Privacy and Press links. Judge the whole supplied group. A generic standalone Learn more outside a paragraph/list/table/associated heading has no programmatically determined purpose merely because the page body discusses a topic; mark failed when the configured specific purpose is otherwise identifiable. Do not treat arbitrary body text as associated context. An empty accessible name is not_applicable here (syntactic link-name), not a second semantic failure. A self-fragment/menu launcher may describe its local context. Do not claim that the remote destination content, language, availability or task was verified. If purpose cannot be established from observed evidence select insufficient_evidence.',
'button-label-mismatch': 'Compare the accessible name with independently supplied configured action, referenced controlled content, title and form context. Submit/reset types, explicit toggle targets and clear configured actions supply purpose; an opaque script/icon/class alone does not establish actual behavior. A clear contradiction is failed; a consistent descriptive name is passed within the configured-purpose scope, not proof of successful action. Missing name is not_applicable (syntactic button-name). An unknown action or ambiguous intent requires insufficient_evidence.',
'widget-label-purpose-mismatch': 'Compare an existing accessible name with the role, controlled panel/content, option group and configured purpose. A tab naming its supplied panel or an option naming its supplied value is passed; a contradictory name is failed. Names on unrelated siblings do not supply the widget purpose. Missing name is not_applicable (syntactic); opaque controls without independent purpose require insufficient_evidence. No interaction success claim.',
'aria-state-mismatch': 'Judge ONLY states with independent rendered_observation evidence: aria-checked versus native checked/indeterminate, aria-selected versus native selected, aria-expanded versus visibility of one unambiguous referenced controlled panel. Matching states are passed, a clear mismatch is failed. Declared ARIA state itself is not a witness; aria-pressed needs independent actual toggle-state evidence and otherwise requires insufficient_evidence. A valid mixed indeterminate checkbox matches mixed. Missing/unresolved controls, ambiguous visibility or unobserved state require insufficient_evidence. No guessing from class names or screen position.',
'table-header-association-mismatch': 'Use the complete observed table, row/column positions, caption, cells and existing headers/scope relationships. Evaluate the current element, not every defect in its table. Explicit headers on a cell override implicit scope associations for that cell. For a scoped th, do not assign a cell to it when that cell explicitly references another header; an unused but meaningful scoped header is not a mismatch. Correct semantic association of data with row/column header meaning is passed; a clearly wrong existing association is failed. An unresolved/missing required header association belongs to syntactic checks and is not_applicable here. Do not infer meaning of absent data. Complex span/layout ambiguity without enough evidence requires insufficient_evidence.',
'error-message-mismatch': 'Compare the referenced existing error message with the field label, type/constraints and observed validity when supplied. A message describing another field or contradicting an independently established required data/constraint is failed; a specific consistent message is passed within this contextual scope. Do not infer actual user input invalidity from aria-invalid alone. Missing referenced message is not_applicable (syntactic relationship). Generic messages with unclear issue or an unknown constraint require insufficient_evidence.'}
