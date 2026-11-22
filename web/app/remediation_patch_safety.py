"""Additional deterministic scope checks for the current preservation-first patches."""
import json
import re
from bs4 import BeautifulSoup
from remediation_structure_contract import assess

PROTECTED_ATTRIBUTES={'href','src','srcset','action','method','name','value','type','form','formaction','formmethod','formenctype','formtarget','enctype','target'}
CSS_PROPERTIES={'color','background-color','outline','outline-color','outline-style','outline-width','outline-offset','border-color','text-decoration','text-decoration-color','text-decoration-style','text-decoration-thickness','text-underline-offset','caret-color','box-shadow','list-style-type'}


def permits_pointer_target_sizing(approach):
    """Keep minimal scope strict; allow bounded control sizing after regeneration."""
    from remediation_interventions import VERSION
    return approach.step == 3 or (
        approach.version == VERSION and
        approach.engine in {'regenerate_html', 'regenerate_markdown'})


def fully_observed_nodes(soup, evidence, *, include_descendants=False):
    """Resolve complete excerpts to source nodes, independent of CSS spelling.

    The recorded match index disambiguates a shared selector. Matching markup
    alone cannot authorize an identical but unobserved node elsewhere.
    Versioned descendant coverage uses only an exact, unabridged ancestor from
    the same current DOM; an overview or a partial excerpt never supplies it.
    """
    observed = set()
    for row in evidence.get('affected_nodes', []):
        if (row.get('html_truncated') or row.get('attributes_truncated')
                or row.get('attributes_abbreviated')):
            continue
        try:
            matches = soup.select(row['selector'])
            # Older complete contexts omitted indices for unique selectors.
            position = row.get('match_index', 1 if len(matches) == 1 else None)
            match_count = row.get('match_count', 1 if len(matches) == 1 else None)
            if (type(position) is not int or not 1 <= position <= len(matches)
                    or match_count != len(matches)):
                continue
            node = matches[position - 1]
            if row.get('html') == str(node):
                observed.add(id(node))
                if include_descendants:
                    observed.update(id(child) for child in node.find_all(True))
        except (KeyError, TypeError, ValueError, SyntaxError):
            continue
    return observed


def rejection_reason(document,operation,approach,base_url,context, *, complete_subtrees=False):
    action=operation.get('action');selector=operation.get('selector','');soup=BeautifulSoup(document,'html.parser')
    name=operation.get('name','').lower()
    if action=='remove_decorative_image':
        from remediation_decorative_resource import removable
        try:nodes=soup.select(selector)
        except Exception:return 'invalid decorative image selector'
        if not nodes or not all(removable(n) for n in nodes):
            return 'only empty one-pixel decorative images without content or control ownership may be removed'
        return None
    if action in {'set_attribute','remove_attribute'} and (name in PROTECTED_ATTRIBUTES or name.startswith('on')):
        return 'source task destinations, native contracts and handlers are protected'
    if action in {'set_attribute','remove_attribute'} and name=='style':
        return 'use a targeted accessibility CSS rule rather than rewriting authored inline styles'
    if action=='set_attribute' and (name in {'hidden','inert'} or name=='aria-hidden' and str(operation.get('value')).lower()=='true' or name=='role' and operation.get('value')in {'none','presentation'}):
        return 'patches cannot conceal content or remove meaningful semantics to improve scores'
    if action=='remove_attribute' and name=='role':
        try:nodes=soup.select(selector)
        except Exception:return 'invalid selector'
        if any(n.name in {'ul','ol'} and any(child.name!='li' or child.get('role')not in (None,'listitem','none','presentation') for child in n.find_all(recursive=False) if child.name not in {'script','template'}) for n in nodes):
            return 'removing an explicit list role does not repair invalid native list children; coordinate the child semantics within the permitted scope'
    if action in {'insert_before','insert_after','append_body_html'}:
        fragment=BeautifulSoup(operation.get('html',''),'html.parser')
        if len(operation.get('html',''))>1600 or len(fragment.find_all(True))>8 or fragment.select('script,style,iframe,form,input,select,textarea,button,main,nav,section,article,header,footer'):
            return 'insertions are bounded adjunct labels/descriptions/skip links, not new behavior, tasks or content regions'
        for link in fragment.select('a[href]'):
            target=link['href']
            if not target.startswith('#') or not soup.find(id=target[1:]):
                return 'an adjunct skip link must target an existing source ID'
    if action=='replace_element':
        try:nodes=soup.select(selector)
        except Exception:return 'invalid replacement selector'
        if not nodes or any(n.name in {'html','head','body','main','nav','header','footer','form'}for n in nodes):
            return 'replacement must address an existing bounded semantic component, not a page or major region'
        if len({str(n)for n in nodes})!=1:return 'one replacement cannot overwrite heterogeneous selector matches'
        try:evidence=json.loads(context)if isinstance(context,str)else(context or {})
        except(ValueError,TypeError):return 'replacement evidence is unavailable'
        observed = fully_observed_nodes(soup, evidence, include_descendants=complete_subtrees)
        if any(id(node) not in observed for node in nodes):
            return 'replacement requires complete supplied evidence for every matched element'
        replacement=operation.get('html','')
        for node in nodes:
            if assess(str(node),replacement,base_url or '')['status']!='passed':
                return 'replacement changes source order or native control ownership/contracts'
    if action=='append_css':
        try:anchors=soup.select(selector)
        except Exception:return 'CSS requires an observed component selector'
        if not anchors or any(n.name in {'html','body'}for n in anchors):return 'global CSS redesign is outside patch scope'
        css=re.sub(r'/\*.*?\*/','',operation.get('css',''),flags=re.S)
        blocks=list(re.finditer(r'([^{}]+)\{([^{}]*)\}',css))
        if not blocks or re.sub(r'([^{}]+)\{([^{}]*)\}','',css).strip():return 'CSS must contain simple scoped rules'
        for block in blocks:
            selectors,body=block.groups()
            rule_targets=[]
            if '@'in selectors:return 'CSS imports and global at-rules are outside patch scope'
            for part in selectors.split(','):
                query=re.sub(r':(?:focus-visible|focus-within|focus|hover|active)\b|::(?:before|after)\b','',part.strip())
                try:targets=soup.select(query)
                except Exception:return 'CSS selector cannot be verified against the source'
                if not targets or any(not any(target is anchor or anchor in target.parents for anchor in anchors)for target in targets):
                    return 'CSS affects elements outside the declared component'
                rule_targets.extend(targets)
            for declaration in body.split(';'):
                if not declaration.strip():continue
                if ':'not in declaration:return 'invalid CSS declaration'
                prop,value=declaration.split(':',1)
                if prop.strip().lower() == 'opacity':
                    # Contrast can remain low despite correct colors when a
                    # source animation fades an ancestor. Restoring opacity
                    # is allowed; hiding or dimming content is never a repair.
                    if not re.fullmatch(r'\s*1(?:\.0+)?\s*(?:!important\s*)?', value, re.I):
                        return 'opacity repairs may restore full visibility only'
                    continue
                if permits_pointer_target_sizing(approach) and prop.strip().lower()=='display':
                    if value.strip().lower().removesuffix('!important').strip() not in {'inline-block','inline-flex'}or any(n.name not in {'a','button','input','label','span','summary'}for n in rule_targets):
                        return 'structural target sizing may change inline control display, not page-region layout'
                    continue
                if permits_pointer_target_sizing(approach) and prop.strip().lower()in {'min-width','min-height'}:
                    if approach.step in {4,5} and any(n.name not in {'a','button','input','label','summary'} for n in rule_targets):
                        return 'regeneration target sizing is limited to observed native controls'
                    if not re.fullmatch(r'\s*(?:\d+(?:\.\d+)?)px\s*(?:!important\s*)?',value,re.I)or not 0<float(re.search(r'\d+(?:\.\d+)?',value).group())<=44:
                        return 'structural pointer-target size repairs require explicit positive pixel minima at most 44px'
                    continue
                if prop.strip().lower()not in CSS_PROPERTIES or re.search(r'url\s*\(|expression\s*\(',value,re.I):
                    return 'patch CSS may correct contrast, focus and semantic list appearance, not redesign layout or fetch assets'
    if action=='append_javascript':
        script=operation.get('javascript','')
        if re.search(r'\b(fetch|XMLHttpRequest|WebSocket|EventSource|eval|Function|localStorage|sessionStorage|indexedDB|sendBeacon|serviceWorker)\b|\blocation\b|(?:window\.)?open\s*\(',script):
            return 'keyboard/focus repair cannot use navigation, network, storage or dynamic execution'
    return None
