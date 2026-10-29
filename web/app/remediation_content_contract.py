"""Lossless resource fallback, separate from accessibility acceptance.

This is deterministic assembly, not evidence of semantic equivalence. Missing
source resources are exposed explicitly rather than silently discarded. Unknown
image descriptions are never invented. It does not certify forms or JS tasks.
"""
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from collections import Counter
import json
import re


def grounded_lighthouse_context(findings, document):
    """Separate patchable nodes from another Lighthouse browser's DOM state.

    Preserve raw reports unchanged. A missing selector is not a repaired audit:
    it is excluded only from the patch prompt, with explicit omission evidence.
    Non-node audits are retained. Invalid CSS is actionable only when an exact,
    unique ID from its original snippet exists in the stored document.
    """
    soup = BeautifulSoup(document, 'html.parser')
    grounded, omitted = [], []
    for finding in findings:
        items, missing = [], []
        for item in finding.get('items', []):
            item = dict(item)
            selector = item.get('selector')
            try:
                matched = not selector or bool(soup.select(selector))
            except Exception:
                snippet = BeautifulSoup(item.get('snippet') or '', 'html.parser').find(id=True)
                identity = snippet.get('id') if snippet else None
                exact = soup.find_all(id=identity) if identity else []
                matched = len(exact) == 1 and exact[0].name == snippet.name
                if matched:
                    item.update(selector='[id='+json.dumps(identity)+']',
                                original_selector=selector,
                                selector_grounding='unique exact snippet ID in stored DOM')
            if matched:
                items.append(dict(item))
            else:
                missing.append(selector)
        if missing:
            omitted.append({'audit': finding.get('audit'), 'selectors': missing,
                            'reason': 'Selector absent or uninterpretable in stored patch document; raw audit retained'})
        if items or not finding.get('items'):
            grounded.append(dict(finding, items=items))
    return grounded, omitted


def select_captured_patch_source(network, rendered, measured_selectors=(), base_url='', replay_context_missing=False):
    """Select the captured DOM when measured targets are absent from the response.

    Never fetch new content or mutate either stored artifact. Ordinary server
    HTML keeps the response-first path, avoiding replay of initialized widgets.
    This decision uses content/selector presence, never accessibility scores.
    """
    def content(document):
        soup = BeautifulSoup(document, 'html.parser')
        body = soup.body
        if body is None:
            return None, None
        for node in list(body.select('script,style,noscript,template')):
            node.decompose()
        return len(body.get_text(' ', strip=True)), len(body.select(
            'a[href],button,input,select,textarea,img[src],iframe[src],video'))
    network_text, network_controls = content(network)
    rendered_text, rendered_controls = content(rendered)
    missing = []
    if measured_selectors:
        response_dom = BeautifulSoup(network, 'html.parser')
        captured_dom = BeautifulSoup(rendered, 'html.parser')
        for selector in dict.fromkeys(measured_selectors):
            try:
                if not response_dom.select(selector) and captured_dom.select(selector):
                    missing.append(selector)
            except Exception:
                continue  # Invalid/cross-frame selectors are not evidence of absence.
    empty_shell = network_text == 0 and network_controls == 0
    if ((empty_shell or missing or replay_context_missing) and rendered_text is not None
            and (rendered_text >= 80 or rendered_controls >= 5)):
        # The captured DOM includes scripts inserted by authored loaders. Loading
        # both executes the children twice (including document.write widgets).
        # Replay the authored roster once; keep non-executable data scripts.
        captured_dom = BeautifulSoup(rendered, 'html.parser')
        response_dom = BeautifulSoup(network, 'html.parser')
        base = urljoin(base_url, (response_dom.find('base') or {}).get('href', base_url))
        def script_key(node):
            return (urljoin(base, node['src']) if node.has_attr('src') else node.get_text().strip(),
                    str(node.get('type', '')).lower())
        roster = Counter(script_key(node) for node in response_dom.select('script'))
        removed = []
        for node in list(captured_dom.select('script')):
            kind = str(node.get('type', '')).lower()
            if kind not in ('', 'module', 'text/javascript', 'application/javascript'):
                continue
            key = script_key(node)
            if roster[key]:
                roster[key] -= 1
            else:
                removed.append({'src': node.get('src'), 'type': kind,
                                'reason': 'Executable script absent from response roster'})
                node.decompose()
        return (str(captured_dom) if removed else rendered), {'version': 'captured-patch-source-v3',
            'selected': 'rendered_snapshot',
            'reason': ('Measured response replay lost acquired content, images or controls' if replay_context_missing else 'Empty network application shell' if empty_shell else 'Measured targets exist only in the captured DOM'),
            'replay_context_missing': bool(replay_context_missing),
            'captured_only_selectors': missing,
            'generated_scripts_removed': removed,
            'network_text_length': network_text, 'network_controls': network_controls,
            'rendered_text_length': rendered_text, 'rendered_controls': rendered_controls}
    return network, None


def captured_widget_replay_warnings(original, evaluated):
    """Measured duplicate-control evidence; never an acceptance gate."""
    def controls(document):
        soup=BeautifulSoup(document,'html.parser'); counts=Counter()
        for select in soup.select('select'):
            if not select.find_parent(class_='bootstrap-select') and 'gt_selector' not in select.get('class',[]):
                continue
            key=(select.get('name') or select.get('aria-label') or select.get('title') or '',
                 tuple((item.get('value'),item.get_text(' ',strip=True)) for item in select.select('option')))
            counts[key]+=1
        return counts
    before,after=controls(original),controls(evaluated)
    from frozen_carousel_replay import carousel_warnings
    return [{'control':key[0],'source_count':count,'rendered_count':after[key],
             'evidence':'same native option data repeated after captured scripts replayed'}
            for key,count in before.items() if after[key]>count] + carousel_warnings(original, evaluated)


def prepare_frozen_widget_replay(document, captured_dom=False):
    """Preserve captured initialized states; normalize response widgets for replay.

    DOM snapshots retain generated controls but not the JS plugin instance.
    Replaying the original scripts then nests duplicate controls. Keep the
    original select and its submission/event attributes, letting the plugin
    initialize once. Unknown wrappers and distinct custom choices are retained.
    This consolidates duplicate presentation text, not native option data.
    """
    soup=BeautifulSoup(document,'html.parser'); evidence=[]
    from frozen_acquired_boot import MARKER, INERT
    if not captured_dom and soup.select('script[' + MARKER + '][type="' + INERT + '"]'):
        # Replaying a prepared snapshot/candidate must neither dehydrate its
        # retained controls nor suspend new repair scripts supplied afterwards.
        return document, evidence
    if not soup.select('script') and not captured_dom: return document,evidence
    if captured_dom:
        # The acquired snapshot is already initialized. Dehydrating widgets
        # and rerunning boot code recreates a different state, often empty.
        from frozen_nested_links import prepare_nested_links
        from frozen_acquired_boot import suspend_acquired_boot
        evidence.extend(prepare_nested_links(soup))
        evidence.extend(suspend_acquired_boot(soup))
        return (str(soup) if evidence else document), evidence
    for owner in list(soup.select('div.bootstrap-select')):
        selects=owner.find_all('select',recursive=False)
        if len(selects)!=1 or owner.select('input,textarea,form'):
            continue
        select=selects[0]
        # Translator code also recreates its native select. Dehydrating only
        # Bootstrap is insufficient for that compound widget (confirmed by
        # browser replay); leave it intact rather than ship a partial fix.
        if 'gt_selector' in select.get('class',[]) or owner.find_parent(class_='gtranslate_wrapper'):
            continue
        children=owner.find_all(True,recursive=False)
        if any(child is not select and not (child.name=='button' and 'dropdown-toggle' in child.get('class',[])) and not (child.name=='div' and 'dropdown-menu' in child.get('class',[])) for child in children):
            continue
        options=Counter(option.get_text(' ',strip=True) for option in select.select('option'))
        listings=owner.select('ul.dropdown-menu')
        if len(listings)!=1 or not options:
            continue
        listing=listings[0]
        if any(str(text).strip() for text in owner.find_all(string=True,recursive=False)):
            continue
        menu=listing.find_parent('div',class_='dropdown-menu')
        if menu is None or menu.get_text(' ',strip=True)!=listing.get_text(' ',strip=True):
            continue
        labels=Counter(li.get_text(' ',strip=True) for li in listing.find_all('li',recursive=False))
        if labels!=options:
            continue
        # A generated caption may repeat only an acquired option label; do
        # not erase independent instructions, live errors or other controls.
        captions=owner.find_all('button',recursive=False)
        if not captions or any(button.get_text(' ',strip=True) not in options for button in captions):
            continue
        identifier=select.get('id'); name=select.get('name')
        if select.get('tabindex')=='-98': select.attrs.pop('tabindex',None)
        select.extract(); owner.replace_with(select)
        evidence.append({'component':'bootstrap-select','id':identifier,'name':name,
            'options':sum(options.values()),'method':'generated wrapper and exact duplicate option list dehydrated; native select retained'})
    from frozen_carousel_replay import prepare_carousels
    evidence.extend(prepare_carousels(soup))
    from frozen_chat_replay import prepare_chat
    evidence.extend(prepare_chat(soup))
    return (str(soup) if evidence else document),evidence


def original_page_wrapper(candidate, source, base_url):
    """Embedding the untouched original is not a corrected full-page output."""
    if not base_url: return False
    canonical=lambda value:urljoin(base_url,value).split('#',1)[0].rstrip('/')
    original=BeautifulSoup(source,'html.parser')
    allowed={canonical(frame.get('src','')) for frame in original.select('iframe[src]')}
    return any(canonical(frame['src'])==canonical(base_url) and canonical(frame['src']) not in allowed
               for frame in BeautifulSoup(candidate,'html.parser').select('iframe[src]'))


def hydrate_static_placeholders(network, rendered):
    """Recover captured static media in empty regions, not initialized widgets.

    Replaying a fully initialized carousel DOM creates duplicate slides. Keep
    network HTML and scripts; hydrate only uniquely matched, media-empty static
    placeholders with captured markup. Unknown identities are left unchanged.
    """
    original=BeautifulSoup(network,'html.parser')
    captured=BeautifulSoup(rendered,'html.parser')
    hydrated=[]
    for node in original.select('section,aside,div,nav'):
        if not any(parent is original for parent in node.parents): continue
        if node.select('a,img,p,li,input,button,select,textarea,iframe,video'):
            continue
        if node.get('id') and len(original.find_all(id=node['id']))==1:
            selector='[id="'+node['id'].replace('"','\\"')+'"]'
        else:
            classes=node.get('class',[])
            if not classes or any(not re.match(r'^[a-zA-Z_][\w-]*$',value) for value in classes): continue
            selector=node.name+''.join('.'+value for value in classes)
        try:
            matches=captured.select(selector)
            if len(matches)!=1 or len(original.select(selector))!=1: continue
        except Exception: continue
        counterpart=matches[0]
        if not counterpart.select('img') or len(counterpart.find_all(True))>120: continue
        if counterpart.select('script,style,input,button,select,textarea,iframe'): continue
        if any(re.search(r'slick|swiper|initialized',value,re.I)
               for item in [counterpart,*counterpart.find_all(True)] for value in item.get('class',[])): continue
        # Preserve the original region identity/style and only fill its contents.
        replacement=BeautifulSoup(str(counterpart),'html.parser').find(counterpart.name)
        node.clear()
        for child in list(replacement.contents): node.append(child.extract())
        node['data-warp-capture-hydrated']='true'
        visible_display=re.search(r'(?:^|;)\s*display\s*:\s*(block|flex|grid|inline-block)\s*(?:;|$)',counterpart.get('style',''),re.I)
        display=visible_display.group(1).lower() if visible_display else 'block'
        style=original.new_tag('style'); style['data-warp-frozen-media']='true'
        style.string=f'{selector}[data-warp-capture-hydrated="true"] {{ display: {display} !important; }}'
        (original.head or original).append(style)
        hydrated.append({'selector':selector,'images':len(node.select('img')),
                         'visible_display':display,
                         'method':'uniquely matched static media placeholder'})
    return str(original),hydrated


def preserve_resources(candidate, source, base_url):
    output=BeautifulSoup(candidate,'html.parser')
    original=BeautifulSoup(source,'html.parser')
    destination=output.body or output
    additions=[]
    present_links={urljoin(base_url,a.get('href')) for a in output.select('a[href]')}
    present_images={urljoin(base_url,i.get('src') or i.get('data-src') or '') for i in output.select('img[src],img[data-src]')}
    section=output.new_tag('section'); section['data-warp-resource-fallback']='true'
    language=(original.html.get('lang','') if original.html else '').lower()
    section['aria-label']='Recursos originales conservados' if language.startswith('es') else 'Retained original resources'
    for anchor in original.select('a[href]'):
        href=anchor.get('href','')
        if href.startswith(('#','javascript:')): continue
        url=urljoin(base_url,href)
        label=anchor.get_text(' ',strip=True) or anchor.get('aria-label') or anchor.get('title')
        if not label:
            label=' '.join(i.get('alt','') for i in anchor.select('img')).strip()
        if url in present_links or not label: continue
        link=output.new_tag('a',href=url); link.string=label
        paragraph=output.new_tag('p'); paragraph.append(link); section.append(paragraph)
        present_links.add(url); additions.append({'kind':'link','url':url,'source_label':label})
    for image in original.select('img[src],img[data-src]'):
        url=urljoin(base_url,image.get('src') or image.get('data-src') or '')
        if not url or url.startswith('data:') or url in present_images: continue
        img=output.new_tag('img',src=url); img['alt']=image.get('alt') or ''
        img['loading']='lazy'; img['style']='max-width:100%;height:auto'
        figure=output.new_tag('figure'); figure.append(img)
        if image.get('title'):
            caption=output.new_tag('figcaption'); caption.string=image['title']; figure.append(caption)
        section.append(figure); present_images.add(url)
        additions.append({'kind':'image','url':url,'source_alt':image.get('alt')})
    if additions: destination.append(section)
    return str(output),additions
