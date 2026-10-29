"""Source-only compatibility helpers; no page skeletons or CSS injection."""
import hashlib
VERSION='source-reference-only-v1'
DESIGN_BASES={'source':('Acquired page evidence',None)}

def selected_framework(selection):
    return 'source'

def intervention_framework(selection, intervention_version, selected_level):
    return 'source'

def select_reference(document,framework='source'):
    if framework!='source':raise ValueError('Prescribed regeneration templates are retired')
    return {'version':VERSION,'framework':'source','design_name':'Acquired page evidence','stylesheet':None,
            'page_type':'source','reason':'No prescribed template','features':{},'html':'',
            'sha256':hashlib.sha256(document.encode()).hexdigest(),'sources':[],
            'source_document_sha256':hashlib.sha256(document.encode()).hexdigest(),
            'provenance':'Acquired source only','certified_accessible':False}

def reference_instruction(reference):
    return 'Use acquired evidence; no template, replacement framework or imposed stylesheet.'

def ensure_design_base(document,framework='source'):
    if framework!='source':raise ValueError('Prescribed regeneration templates are retired')
    return document,{'framework':'source','design_name':'Acquired page evidence','stylesheet':None,'changes':[]}
