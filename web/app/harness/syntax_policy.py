"""Baseline-relative syntax evidence; raw validator findings are never rewritten."""
from collections import Counter
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from soupsieve import SelectorSyntaxError

VERSION = 'source-relative-syntax-v5'


def localize(syntax, document, base_url):
    """Add source-derived task identities without altering validator findings.

    Anchored image-input and button descendants carry source-derived task
    identities. Exact inherited BODY metadata also carries an attribute hash,
    so removing a sibling cannot invent a new error. Other rules retain their
    exact selector identity.
    """
    soup = BeautifulSoup(document, 'html.parser')
    identities = {}
    boundary_contracts = {}
    for error in syntax.get('errors', []):
        if error.get('rule')=='close-order' and error.get('message')=="Stray end tag '</head>'" and not error.get('selector'):
            # Only a located, exact closing token with identical raw neighbours
            # can inherit this unlocalized source error. Counts alone cannot.
            line,column=error.get('line'),error.get('column')
            lines=document.splitlines(keepends=True)
            if type(line)is int and type(column)is int and 0<line<=len(lines)and column>0:
                try:
                    prefix=lines[line-1].encode('utf-16-le')[:2*(column-1)].decode('utf-16-le')
                    offset=sum(len(part)for part in lines[:line-1])+len(prefix)
                    import re,hashlib
                    match=next((m for m in re.finditer(r'</head\s*>',document,re.I)if abs(m.start()-offset)<=2),None)
                    if match:
                        anchor=document[max(0,match.start()-96):match.start()]+'|'+match.group().lower()+'|'+document[match.end():match.end()+96]
                        boundary_contracts[str(line)+':'+str(column)]=['raw-head-boundary-v1',hashlib.sha256(anchor.encode()).hexdigest()]
                except (UnicodeError,ValueError):pass

        context=error.get('context',{})
        if (error.get('rule')=='element-permitted-content' and context.get('kind')=='content'
                and context.get('child')=='<meta>' and context.get('parent')=='<body>'):
            selector=error.get('selector')
            try: matches=soup.select(selector) if isinstance(selector,str)and selector else []
            except (SelectorSyntaxError,NotImplementedError):matches=[]
            if len(matches)==1 and matches[0].name=='meta' and matches[0].parent.name=='body':
                import hashlib,json
                attributes=json.dumps(dict(matches[0].attrs),sort_keys=True,separators=(',',':'),ensure_ascii=False)
                identities[selector]=['inherited-body-metadata-v1',hashlib.sha256(attributes.encode()).hexdigest()]
            continue
        if error.get('rule')!='element-permitted-content' or context.get('ancestor')!='<a>' or context.get('kind')!='descendant' or context.get('child') not in ('<input>','<button>'):
            continue
        selector = error.get('selector')
        if not isinstance(selector, str) or not selector:
            continue
        try:
            matches = soup.select(selector)
        except (SelectorSyntaxError, NotImplementedError):
            continue
        if len(matches) != 1:
            continue
        control = matches[0]
        anchor = control.find_parent('a')
        if not anchor or not anchor.get('href'):
            continue
        if control.name=='input' and control.get('type')=='image' and control.get('src'):
            identities[selector]=['anchored-image-input-v1',control.get('name'),control.get('value'),
                                  urljoin(base_url,control['src']),urljoin(base_url,anchor['href'])]
        elif control.name=='button':
            identities[selector]=['anchored-button-v1',control.get('type','submit'),control.get('name'),
                                  control.get('value'),urljoin(base_url,anchor['href'])]
    return {**syntax, 'localized_contracts': identities,'document_boundary_contracts':boundary_contracts}


def compare(candidate, baseline=None):
    candidate = candidate or {}
    result = {'policy': VERSION, 'state': 'unverified', 'inherited': [], 'introduced': []}
    if candidate.get('state') == 'passed':
        return result | {'state': 'passed'}
    if baseline is None:
        return result | {'state': candidate.get('state', 'unverified'),
                         'introduced': candidate.get('errors', [])}
    if candidate.get('state') != 'violated' or baseline.get('state') not in ('passed', 'violated'):
        return result
    if not candidate.get('validator') or any(candidate.get(k) != baseline.get(k) for k in ('validator','version')):
        return result
    errors = candidate.get('errors'); previous = baseline.get('errors')
    if not isinstance(errors,list) or not errors or not isinstance(previous,list):
        return result
    def identity(error, syntax):
        if isinstance(error,dict)and error.get('rule')=='close-order'and error.get('message')=="Stray end tag '</head>'"and not error.get('selector'):
            boundary=syntax.get('document_boundary_contracts',{}).get(str(error.get('line'))+':'+str(error.get('column')))
            if isinstance(boundary,list)and len(boundary)==2 and boundary[0]=='raw-head-boundary-v1'and isinstance(boundary[1],str)and len(boundary[1])==64:
                return(error['rule'],error['message'],tuple(boundary))
        if not isinstance(error,dict) or not all(isinstance(error.get(k),str) and error[k] for k in ('rule','message','selector')):
            raise ValueError('Unlocalized syntax finding')
        contract = syntax.get('localized_contracts', {}).get(error['selector'])
        if (isinstance(contract,list) and len(contract)==2 and contract[0]=='inherited-body-metadata-v1'
                and isinstance(contract[1],str) and len(contract[1])==64
                and error.get('rule')=='element-permitted-content'
                and error.get('context',{})=={'child':'<meta>','kind':'content','parent':'<body>'}):
            return(error['rule'],error['message'],tuple(contract))
        if isinstance(contract, list) and len(contract) == 5 and contract[0] in ('anchored-image-input-v1','anchored-button-v1') and all(value is None or isinstance(value, str) for value in contract):
            return (error['rule'], error['message'], tuple(contract))
        return tuple(error[k] for k in ('rule','message','selector'))
    try:
        available = Counter(identity(error, baseline) for error in previous)
        for error in errors:
            key = identity(error, candidate)
            if available[key]:
                available[key] -= 1; result['inherited'].append(error)
            else:
                result['introduced'].append(error)
    except ValueError:
        return result | {'inherited': [], 'introduced': []}
    return result | {'state': 'violated' if result['introduced'] else 'passed'}
