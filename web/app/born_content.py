"""Content-locked regeneration: model-owned layout, source-owned content.

This is an assembly contract, not an accessibility certification or semantic
review gate. Original application scripts are not portable; expose that limit.
"""
import json
import re
from collections import Counter
from bs4 import BeautifulSoup, Comment
from urllib.parse import urljoin
from born_media import mark_footer_media, FOOTER_MEDIA_CSS

READABLE_CONTENT_CSS='''body{line-height:1.65} .warp-content-block{min-width:0;margin-block:1rem}
body>header,body>main,body>footer{max-width:72rem;margin-inline:auto;padding:1.25rem clamp(1rem,3vw,2rem)}
.warp-content-block img.warp-brand-image{width:min(100%,22rem);height:auto}
.warp-content-block nav>ul{display:flex;flex-wrap:wrap;gap:1rem 2rem;list-style:none;padding-inline:0}
.warp-content-block img{max-width:100%;height:auto;object-fit:contain}
.warp-content-block :where(p,ul,ol,figure,form){margin-block:.75rem}
.warp-content-block :where(h1,h2,h3,h4,h5,h6){margin-block:1.25rem .5rem}
.warp-content-block :where(input,select,textarea){max-width:100%}
.warp-content-block :where(a,td,th){overflow-wrap:anywhere}
.warp-content-block a{color:inherit;text-decoration:underline}
.warp-content-block svg.warp-icon{width:2rem;height:2rem;vertical-align:middle}
.warp-content-block svg{max-width:100%}
:focus-visible{outline:3px solid #18529d;outline-offset:3px}'''+FOOTER_MEDIA_CSS


def ensure_primary_heading(document, source_title):
    """Use the acquired title when a reconstructed document omitted all h1s."""
    if not source_title or not source_title.strip(): return document
    soup=BeautifulSoup(document,'html.parser')
    if soup.select('h1') or not soup.select_one('main'): return document
    heading=soup.new_tag('h1'); heading.string=source_title.strip()
    heading['class']=['h2','mb-4']; heading['data-warp-heading-origin']='frozen-document-title'
    soup.select_one('main').insert(0,heading)
    return str(soup)


def validate_layout_css(css):
    if re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden|opacity\s*:\s*0\s*[;}])',css,re.I):
        raise ValueError('Born layout CSS must not conceal source content')


def unique_identifiers(soup):
    """Disambiguate captured copies without dropping their text or controls.

    The first original id stays stable. Rewrite references only inside a
    subtree containing exactly one copy, never guess at global ownership.
    """
    seen=set(); occupied={node['id'] for node in soup.select('[id]')}
    for node in soup.select('[id]'):
        old=node['id']
        if old not in seen:
            seen.add(old); continue
        number=2; new=f'{old}-warp-copy-{number}'
        while new in occupied:
            number+=1; new=f'{old}-warp-copy-{number}'
        scope=node
        for parent in node.parents:
            if len(parent.find_all(id=old))!=1: break
            scope=parent
        node['id']=new; occupied.add(new)
        for target in [scope,*scope.find_all(True)]:
            for name in ('for','aria-labelledby','aria-describedby'):
                if target.get(name): target[name]=' '.join(new if value==old else value for value in target[name].split())
            if target.get('href')=='#'+old: target['href']='#'+new


def readable_fragment(source, base_url):
    soup=BeautifulSoup(source,'html.parser')
    for node in soup.select('script,style,noscript,template'):
        node.decompose()
    for comment in soup.find_all(string=lambda value:isinstance(value,Comment)):
        comment.extract()
    # Remove only proven captured navigation copies. Retain the original menu,
    # never consolidate a footer or merely similar navigation by intuition.
    navigations=soup.select('nav')
    signature=lambda node:(node.get_text(' ',strip=True),tuple((a.get('href'),a.get_text(' ',strip=True)) for a in node.select('a[href]')))
    for navigation in navigations:
        identity=navigation.get('id','')+' '+' '.join(navigation.get('class',[]))
        if not re.search(r'clon(?:e|ed)',identity,re.I) or navigation.select('form,input,select,textarea'): continue
        original=next((other for other in navigations if other is not navigation and other.parent is not None and not re.search(r'clon(?:e|ed)',other.get('id','')+' '+' '.join(other.get('class',[])),re.I) and signature(other)==signature(navigation)),None)
        if original:
            original['data-warp-captured-copy-consolidated']='true'
            navigation.decompose()
    # Captured custom selects contain both native options and a JS popup copy.
    # Preserve the copy as an explicit native disclosure, not a 100-item menu
    # permanently expanded before the actual page. Only exact option matches
    # qualify; unrelated lists and their reading order remain unchanged.
    for select in soup.select('select'):
        options=Counter(option.get_text(' ',strip=True) for option in select.select('option'))
        owner=next((parent for parent in select.parents if getattr(parent,'attrs',None) is not None and 'bootstrap-select' in parent.get('class',[])),None)
        if not owner or not options: continue
        for listing in owner.select('ul'):
            labels=Counter(li.get_text(' ',strip=True) for li in listing.find_all('li',recursive=False))
            if labels!=options: continue
            disclosure=soup.new_tag('details'); disclosure['data-warp-static-disclosure']='original-option-list'
            summary=soup.new_tag('summary'); summary.string=select.get('aria-label') or select.get('title') or next(iter(options))
            listing.replace_with(disclosure); disclosure.append(summary); disclosure.append(listing)
        if not select.find_parent('form'):
            select['disabled']=''; select['data-warp-static-control']='application-script-not-ported'
    for node in soup.find_all(True):
        source_classes=node.get('class',[])
        # Identify records before retiring the source theme. These are hints
        # for a deterministic renderer, not permission to invent data.
        if node.name=='article' or any(value in {'card','teaser','views-row'} or value.startswith('node--view-mode-teaser') for value in source_classes):
            if node.select('a[href]') and node.select('h1,h2,h3,h4,h5,h6,img'):
                node['data-warp-source-kind']='card'
        elif any(value in {'carousel-item','slide'} for value in source_classes):
            node['data-warp-source-kind']='slide'
        grid_classes=[value for value in source_classes if value=='row' or re.fullmatch(r'col-(?:(?:sm|md|lg|xl|xxl)-)?(?:[1-9]|1[0-2])',value)]
        # Frozen interactive state and original theme must not hide content in
        # the new document. Preserve native fields, options and submission data.
        for name in list(node.attrs):
            if name in {'class','style','hidden','inert','autofocus','role','tabindex','aria-hidden','aria-expanded','aria-controls','aria-owns','aria-selected','aria-activedescendant','aria-haspopup','aria-disabled'} or name.startswith(('on','data-bs-')):
                del node.attrs[name]
        if grid_classes: node['class']=grid_classes+(['g-4'] if 'row' in grid_classes else [])
        if node.name=='svg':
            try:
                bounds=[float(value) for value in node.get('viewBox',node.get('viewbox','')).split()]
                if len(bounds)==4 and max(bounds[2:])<=64: node['class']='warp-icon'
            except ValueError: pass
        if node.name in {'html','head','body','main','header','footer'}:
            if node.name=='header': node['data-warp-source-landmark']='header'
            node.name='div'
        for name in ('href','src','action','poster'):
            value=node.get(name)
            if value and not value.startswith(('#','data:','javascript:')):
                node[name]=urljoin(base_url,value)
        if node.name=='img':
            node['src']=urljoin(base_url,node.get('data-src') or node.get('src') or '')
            if not node.has_attr('alt'): node['alt']=''
            if node.get('alt','').casefold() in {'home','inicio'} and any(parent.get('data-warp-source-landmark')=='header' for parent in node.parents if getattr(parent,'attrs',None) is not None):
                node['class']='warp-brand-image'
        if node.name=='details' and not node.has_attr('data-warp-static-disclosure'): node['open']=''
        if node.name in {'audio','video'}:
            node.attrs.pop('autoplay',None)
            node['controls']=''
        # A static rendition must not advertise dead theme/widget controls.
        # Keep their wording but only leave native form buttons interactive.
        if node.name=='button' and not node.find_parent('form') and not node.get('form'):
            node.name='span'
            for name in ('type','disabled','aria-pressed'): node.attrs.pop(name,None)
        if node.name=='a' and node.get('href','').startswith('javascript:'):
            node.name='span'; node.attrs.pop('href',None)
        if node.name=='input' and node.get('type')=='hidden':
            continue
        if node.name in {'input','select','textarea'}:
            node['class']='form-select' if node.name=='select' else 'form-check-input' if node.get('type') in {'checkbox','radio'} else 'form-control'
        if node.name=='button': node['class']='btn btn-outline-primary'
    # Source list/table structure is retained rather than flattening its words.
    unique_identifiers(soup)
    return str(soup)


def content_manifest(components, base_url, verified_components=False):
    manifest=[]
    for item in components:
        fragment=readable_fragment(item['source'],base_url)
        if item['area']=='footer':
            footer=BeautifulSoup(fragment,'html.parser'); mark_footer_media(footer)
            fragment=str(footer)
        evidence=None
        if verified_components:
            from born_components import render_components
            fragment,evidence=render_components(fragment,item['area'])
        soup=BeautifulSoup(fragment,'html.parser')
        from born_composition import composition_payload
        composition=composition_payload(fragment,item['id']) if evidence else None
        manifest.append({'id':item['id'],'area':item['area'],
                         'purpose':item.get('reason') or item.get('identity') or item['element'],
                         'headings':[node.get_text(' ',strip=True) for node in soup.select('h1,h2,h3,h4,h5,h6')],
                         'preview':soup.get_text(' ',strip=True)[:1200],
                         'words':len(soup.get_text(' ',strip=True).split()),
                         'images':len(soup.select('img')),'forms':len(soup.select('form')),
                         'html':fragment,**({'component_renderer':evidence,'composition_units':composition['units'],'composition_shells':composition['shells']} if evidence else {})})
    return manifest


def coherent_regions(components):
    """Project region recommendations onto a single ordered document shell.

    Source order/content never changes. A late header is part of main; trailing
    auxiliary components after footer are footer content, not a second main.
    Keep the agent recommendation for the evidence trail.
    """
    result=[]; phase=0
    regions={'header':0,'main':1,'footer':2}
    for component in components:
        proposed=component['area']
        phase=max(phase,regions[proposed])
        result.append({**component,'planner_area':proposed,'area':('header','main','footer')[phase]})
    return result


def manifest_context(manifest):
    return json.dumps([{key:([{k:v for k,v in unit.items() if k!='html'} for unit in value] if key=='composition_units' else value) for key,value in item.items() if key!='html'} for item in manifest],ensure_ascii=False)


def layout_only(document):
    soup=BeautifulSoup(document,'html.parser')
    for asset in soup.select('[data-warp-framework]'): asset.decompose()
    for slot in soup.select('[data-warp-slot]'):
        units=slot.select('[data-warp-unit]')
        if units:
            for unit in units: unit.clear()
            for shell in slot.select('[data-warp-composition-shell]'): shell.unwrap()
        else: slot.clear()
    return str(soup)


def bind_content(document, manifest, fragment=False, document_title=None):
    """Require exactly one empty, visible slot per component, in frozen order."""
    soup=BeautifulSoup(document,'html.parser')
    if not fragment and (not soup.html or not soup.head or not soup.body):
        raise ValueError('Born layout must be a complete document')
    slots=soup.select('[data-warp-slot]')
    required=[item['id'] for item in manifest]
    found=[node.get('data-warp-slot') for node in slots]
    if Counter(found)!=Counter(required) or found!=required:
        raise ValueError(f'Born layout slots must equal {required} in that exact order; received {found}')
    if not fragment and len(soup.select('main'))!=1:
        raise ValueError('Born layout must own exactly one main landmark')
    if soup.select('script'):
        raise ValueError('Protected layout cannot inject an external behavior dependency')
    if soup.select('iframe,object,embed,meta[http-equiv="refresh"]'):
        raise ValueError('Born layout must not substitute embedded pages or redirects for content slots')
    validate_layout_css('\n'.join(node.get_text() for node in soup.select('style'))+'\n'+'\n'.join(node.get('style','') for node in soup.find_all(True)))
    reference=' '.join(item['preview']+' '+' '.join(item['headings']) for item in manifest).casefold()
    allowed={'skip to main content','skip to content','saltar al contenido','saltar al contenido principal'}
    if soup.title: allowed.add(soup.title.get_text(' ',strip=True).casefold())
    root=soup.body or soup
    for text in root.find_all(string=True):
        if isinstance(text,Comment) or text.parent.name in {'script','style'}: continue
        value=' '.join(str(text).split()).casefold()
        title=soup.title.get_text(' ',strip=True).casefold() if soup.title else ''
        if value and value not in allowed and value not in reference and value not in title:
            raise ValueError('Born layout introduced non-source text; only original headings/title and skip-link wording are allowed outside slots')
    for slot,item in zip(slots,manifest):
        composed=bool(item.get('composition_units') and slot.select('[data-warp-unit]'))
        if item.get('require_composition') and not composed:
            raise ValueError('Step 5 requires semantic-unit composition, not an empty legacy content block')
        if not composed and (slot.get_text(strip=True) or slot.find(True)):
            raise ValueError('Content slots must be empty; original content is supplied by the assembler')
        if slot.name not in {'div','section','article'}:
            raise ValueError('Content slot must be a block container')
        if slot.find_parent(attrs={'data-warp-slot':True}):
            raise ValueError('Content slots must not be nested')
        if any(node.has_attr('hidden') or node.has_attr('inert') or node.get('aria-hidden')=='true' for node in [slot,*slot.parents] if getattr(node,'attrs',None) is not None):
            raise ValueError('Original content slots must not be hidden')
        for ancestor in [slot,*slot.parents]:
            classes=ancestor.get('class',[]) if getattr(ancestor,'attrs',None) is not None else []
            if any(re.fullmatch(r'd-(?:(?:sm|md|lg|xl|xxl)-)?none',name) or name in {'invisible','visually-hidden','collapse'} for name in classes):
                raise ValueError('Original content slots must remain visible, including at narrow widths')
        if composed:
            from born_composition import bind_composition
            bind_composition(slot,item['composition_units'],item.get('composition_shells',[]))
        else:
            content=BeautifulSoup(item['html'],'html.parser')
            for child in list(content.contents): slot.append(child.extract())
        slot['data-warp-component']=item['id']
        slot['class']=list(slot.get('class',[]))+['warp-content-block']
    unique_identifiers(soup)
    if fragment: return str(soup)
    previous=0; first_h1=False
    for heading in soup.select('h1,h2,h3,h4,h5,h6'):
        level=int(heading.name[1])
        if level==1 and first_h1: level=2
        if level==1: first_h1=True
        if previous and level>previous+1: level=previous+1
        heading.name='h'+str(level); previous=level
    style=soup.new_tag('style'); style['data-warp-readable-content']='true'
    style.string=READABLE_CONTENT_CSS
    if any(item.get('component_renderer') for item in manifest):
        from born_components import COMPONENT_CSS
        style.string+='\n'+COMPONENT_CSS
    soup.head.append(style)
    return ensure_primary_heading(str(soup),document_title)
