"""Observed source order and form ownership, independent of audit scores."""
from collections import Counter
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

VERSION='source-order-native-ownership-v2'


def evidence(document, base_url):
    soup=BeautifulSoup(document,'html.parser')
    text=BeautifulSoup(document,'html.parser')
    for node in text.select('head,script,style,noscript,template'):node.decompose()
    words=re.findall(r'\w+',text.get_text(' ',strip=True).casefold())
    controls=Counter()
    forms=soup.select('form')
    flags={'checked','disabled','multiple','required','selected'}
    def attribute(node,key):
        if key in flags:return node.has_attr(key)
        value=node.get(key)
        if key in ('method','type','formmethod','formenctype') and isinstance(value,str):return value.lower()
        return tuple(value)if isinstance(value,list)else value
    for node in soup.select('input,button,select,textarea'):
        form=node.find_parent('form')
        declared=node.get('form')
        if declared:
            found=soup.find_all('form',id=declared)
            form=found[0]if len(found)==1 else None
        owner=(urljoin(base_url,form.get('action',base_url)),form.get('method','get').lower(),form.get('id')or 'form-'+str(next(i for i,f in enumerate(forms)if f is form)))if form else ('unresolved:'+declared if declared else 'outside-form','','')
        contract=(node.name,node.get('name'),node.get('type','text').lower()if node.name=='input'else node.get('type','submit').lower()if node.name=='button'else None,
                  node.get('value'),tuple((key,attribute(node,key))for key in ('checked','disabled','multiple','required','formaction','formmethod','formenctype','formtarget')),tuple((option.get('value'),option.get_text(' ',strip=True),attribute(option,'selected'),attribute(option,'disabled'))for option in node.select('option')))
        controls[(owner,contract)]+=1
    return words,controls


def assess(original,candidate,base_url):
    before,original_controls=evidence(original,base_url)
    after,candidate_controls=evidence(candidate,base_url)
    position=0
    for word in after:
        if position<len(before)and word==before[position]:position+=1
    missing=original_controls-candidate_controls
    preserved_order=position==len(before)
    return {'version':VERSION,'status':'passed'if preserved_order and not missing else 'violated',
            'source_word_order_preserved':preserved_order,
            'source_word_count':len(before),'matched_source_word_prefix':position,
            'missing_native_control_ownership':[{'owner':owner,'control':control,'count':count}for(owner,control),count in missing.items()],
            'scope':'Declared document word order and native form ownership; not visual region equivalence, backend success or unobserved handlers.'}
