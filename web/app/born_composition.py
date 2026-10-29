"""Source-owned semantic units, model-owned Bootstrap composition (step 5).

Flatten only presentation containers without resource/control relationships.
Forms, lists, tables, linked media and unknown structures remain indivisible.
"""
from bs4 import BeautifulSoup, NavigableString

def composition_units(document, component_id):
    soup=BeautifulSoup(document,'html.parser'); units=[]
    def visit(node):
        if isinstance(node,NavigableString):
            if not str(node).strip(): return
        elif node.name in {'div','section'} and not any(key not in {'class'} and not key.startswith('data-warp-') for key in node.attrs) and not node.has_attr('data-warp-source-kind') and not node.has_attr('data-warp-renderer'):
            for child in node.contents: visit(child)
            return
        key=f'{component_id}-u{len(units)}'
        local=BeautifulSoup(str(node),'html.parser')
        units.append({'id':key,'kind':getattr(node,'name',None) or 'text',
                      'text':local.get_text(' ',strip=True),
                      'images':[{'url':img.get('src'),'alt':img.get('alt')} for img in local.select('img')],
                      'links':[{'url':link.get('href'),'label':link.get_text(' ',strip=True)} for link in local.select('a[href]')],
                      'html':str(node)})
    for child in soup.contents: visit(child)
    return units


def composition_payload(document, component_id):
    """Keep source anchor containers, but expose their interior for composition."""
    soup=BeautifulSoup(document,'html.parser'); shells=[]
    while True:
        children=soup.find_all(True,recursive=False)
        if len(children)!=1 or any(str(text).strip() for text in soup.find_all(string=True,recursive=False)): break
        root=children[0]
        if root.name!='div' or root.get('data-warp-source-kind') or root.get('data-warp-renderer') not in {None,'footer'}: break
        if any(key not in {'id','class'} and not key.startswith('data-warp-') for key in root.attrs): break
        shells.append({'tag':'div','attributes':dict(root.attrs)})
        root.unwrap()
    return {'units':composition_units(str(soup),component_id),'shells':shells}


def bind_composition(slot, units, shells=()):
    nodes=slot.select('[data-warp-unit]')
    if [node.get('data-warp-unit') for node in nodes]!=[unit['id'] for unit in units]:
        raise ValueError('Composition must use every owned semantic unit once in source order')
    allowed={'div','section','article'}
    for element in slot.find_all(True):
        if element.name not in allowed or any(key not in {'class','data-warp-unit'} for key in element.attrs):
            raise ValueError('Composition wrappers may contain only semantic layout tags and Bootstrap classes')
        if any(name in {'collapse','invisible','visually-hidden'} or name=='d-none' or name.endswith('-none') for name in element.get('class',[])):
            raise ValueError('Composition must not conceal owned content')
    if slot.get_text(strip=True): raise ValueError('Composition may not invent source text')
    for node,unit in zip(nodes,units):
        if node.get_text(strip=True) or node.find(True) or node.find_parent(attrs={'data-warp-unit':True}):
            raise ValueError('Semantic unit references must be empty and not nested')
        content=BeautifulSoup(unit['html'],'html.parser')
        for child in list(content.contents): node.append(child.extract())
    for shell in reversed(shells):
        wrapper=BeautifulSoup('','html.parser').new_tag(shell['tag'],attrs=shell['attributes'])
        wrapper['data-warp-composition-shell']='true'
        for child in list(slot.contents): wrapper.append(child.extract())
        slot.append(wrapper)


COMPOSITION_INSTRUCTION='''STEP 5 SEMANTIC COMPOSITION CONTRACT:
Emit exactly one outer div/section/article data-warp-slot="component id" for EVERY manifest component, once, in listed order, not nested. Put those slots in the coordinated header, exactly one main, and footer. Within EACH slot design its INTERNAL Bootstrap layout using the listed composition_units. Emit EVERY unit exactly once, in listed order, as an EMPTY div data-warp-unit="unit id". Example structure (use actual ids): <section data-warp-slot="cX"><div class="row g-4"><div class="col-12 col-md-6" data-warp-unit="cX-u0"></div><div class="col-12 col-md-6" data-warp-unit="cX-u1"></div></div></section>.
The assembler supplies original text, media, links and controls. Group related adjacent units into coherent hero columns, cards, responsive rows and footer groups. INSIDE slots ONLY div, section, article tags are permitted, ONLY class and data-warp-unit attributes. Do not create nav/aside/header/footer/form/a/img tags inside slots; source-owned units already supply their semantic structures. Source shell ids/attributes are reinstated automatically; do not copy composition_shells into your output. Do not write source text into unit references. Form/navigation/list/table units are indivisible; never split their relationships. No invented text, links, controls, JavaScript, hiding or fixed-height clipping. Unknown complex units remain intact. Aim for a complete intentional Bootstrap page, not a raw linear document or a card around every paragraph.'''
