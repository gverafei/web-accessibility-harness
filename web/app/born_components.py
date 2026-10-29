"""Versioned Bootstrap renderers with executable preservation contracts.

Verified means tested rendering/data invariants, NOT WCAG certification.
Unknown content retains its semantic structure; no inferred facts or tasks.
"""
from bs4 import BeautifulSoup
import re
from born_media import mark_footer_media

VERSION = 'bootstrap-content-components-v1'
COMPONENT_CSS = '''
[data-warp-renderer="cards-grid"]{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,18rem),1fr));gap:1.5rem;align-items:start}
[data-warp-renderer="card"]{min-width:0;height:auto;background:#fff;color:#17212b}
[data-warp-renderer="card"] img{width:100%;max-height:22rem;object-fit:contain}
[data-warp-renderer="navigation"] ul{list-style:none;padding-inline-start:0}
[data-warp-renderer="navigation"] ul ul{padding-inline-start:1rem}
[data-warp-renderer="navigation"] a{display:inline-block;padding:.4rem .2rem}
[data-warp-renderer="footer"]{padding-block:1rem}
[data-warp-renderer="footer"] svg{width:1.75rem!important;height:1.75rem!important;max-width:1.75rem!important;vertical-align:middle}
[data-warp-renderer="footer"] img[data-warp-icon]{width:1.75rem!important;height:1.75rem!important;object-fit:contain;vertical-align:middle}
[data-warp-renderer="footer"] img[data-warp-brand]{width:min(100%,22rem);height:auto}
[data-warp-renderer="footer"] a:has(svg){display:inline-flex;align-items:center;gap:.5rem;padding:.5rem}
[data-warp-renderer="footer"] a:has(img[data-warp-icon]){display:inline-flex;align-items:center;gap:.5rem;padding:.5rem}
[data-warp-renderer="disclosure"]>summary{padding:.75rem;cursor:pointer}
'''


def data_contract(soup):
    """Ordered text, resources, control state and explicit relationships."""
    attributes = ('href','src','srcset','poster','action','method','name','value',
                  'type','checked','selected','multiple','required','disabled',
                  'alt','title','aria-label','aria-labelledby','aria-describedby','aria-controls',
                  'for','id','form','formaction','formmethod','enctype','autocomplete',
                  'min','max','step','pattern','minlength','maxlength','accept',
                  'scope','headers','rowspan','colspan','target','rel','download')
    return (
        tuple(str(text).strip() for text in soup.stripped_strings),
        tuple(tuple((key,tuple(value) if isinstance(value,list) else value)
                    for key in attributes if (value:=node.get(key)) is not None)
              for node in soup.find_all(True)
              if any(node.has_attr(key) for key in attributes)),
        tuple((node.name,node.get_text()) for node in soup.select('option,textarea')),
    )


def classes(node, *values):
    node['class'] = list(dict.fromkeys([*node.get('class',[]),*values]))


def render_components(document, area):
    soup=BeautifulSoup(document,'html.parser')
    before=data_contract(soup)
    counts={}
    def mark(node,kind):
        node['data-warp-renderer']=kind
        counts[kind]=counts.get(kind,0)+1

    for nav in soup.select('nav'):
        classes(nav,'navbar','d-block','mb-4'); mark(nav,'navigation')
        for listing in nav.find_all(['ul','ol'],recursive=False):
            classes(listing,'nav','gap-3','align-items-start')
        for link in nav.select('a[href]'): classes(link,'nav-link')
    for form in soup.select('form'):
        classes(form,'mb-4'); mark(form,'form')
        for label in form.select('label'): classes(label,'form-label')
        for button in form.select('button'): classes(button,'btn','btn-primary')
    for table in soup.select('table'):
        classes(table,'table','table-striped'); mark(table,'table')
        # Do not alter headers/captions or nesting of data relationships.
    for details in soup.select('details'):
        classes(details,'border','rounded-3','mb-3'); mark(details,'disclosure')
    cards=[]
    for node in soup.select('[data-warp-source-kind="card"], [data-warp-source-kind="slide"]'):
        # Never turn a form/table or nested record into an unrelated card.
        if node.find_parent(attrs={'data-warp-source-kind':['card','slide']}) or node.select('form,table'):
            continue
        classes(node,'card','border-0','shadow-sm','overflow-visible'); mark(node,'card')
        node['class']=[value for value in node['class'] if not value.startswith('col-')]
        body=soup.new_tag('div'); body['class']=['card-body']
        for child in list(node.contents): body.append(child.extract())
        node.append(body); cards.append(node)
    for parent in {id(node.parent):node.parent for node in cards}.values():
        # Only grid homogeneous collections; never grid a heading/form with
        # records or convert an ordered list into a differently ordered set.
        children=parent.find_all(True,recursive=False)
        if len(children)>1 and all(child.get('data-warp-renderer')=='card' for child in children) and not any(str(text).strip() for text in parent.find_all(string=True,recursive=False)):
            parent['class']=[value for value in parent.get('class',[]) if value!='row' and not re.fullmatch(r'g[xy]?-\d+',value)]
            mark(parent,'cards-grid')
    if area=='footer':
        wrapper=soup.new_tag('div'); classes(wrapper,'container-fluid','px-0')
        mark(wrapper,'footer')
        for child in list(soup.contents): wrapper.append(child.extract())
        soup.append(wrapper)
        mark_footer_media(wrapper)
    if data_contract(soup)!=before:
        raise ValueError('Component renderer changed protected content data')
    return str(soup),{'version':VERSION,'framework':'Bootstrap 5.3.8',
        'components':counts,'contract':'ordered-text-resources-controls-relationships',
        'verified':'executable preservation tests; not an accessibility certification'}
