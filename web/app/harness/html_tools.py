"""Reusable source-owned DOM inventories and scoped patch operations."""
import html as html_lib
import json
import re
from collections import Counter
from difflib import SequenceMatcher
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, parse_qsl, urlencode
from bs4 import BeautifulSoup

def insert_head_metadata(soup,node):
    """Keep new metadata before authored flow content that closes the HTML head.

    html.parser keeps custom nodes inside head; browser/validator tree builders
    close head before those nodes. Preserve authored nodes and CSS verbatim.
    """
    from bs4 import Comment
    permitted={'base','link','meta','title','style','script','noscript','template'}
    head=soup.head
    if head is None:
        head=soup.new_tag('head')
        (soup.html or soup).insert(0,head)
    if getattr(node,'name',None)not in permitted:raise ValueError('Head repair must be metadata, not page content')
    node.extract()
    boundary=next((child for child in head.contents if not isinstance(child,Comment)and
        (getattr(child,'name',None)not in permitted if getattr(child,'name',None)else bool(str(child).strip()))),None)
    if boundary is None:head.append(node)
    else:boundary.insert_before(node)


def insert_head_markup(soup,markup):
    """Validate the entire new metadata fragment before changing the document."""
    from bs4 import Comment
    permitted={'base','link','meta','title','style','script','noscript','template'}
    fragment=BeautifulSoup(markup,'html.parser')
    nodes=list(fragment.contents)
    if any((node.name not in permitted)if getattr(node,'name',None)else(bool(str(node).strip())and not isinstance(node,Comment))for node in nodes):
        raise ValueError('Head repair must contain metadata only')
    for node in nodes:
        if getattr(node,'name',None):insert_head_metadata(soup,node)


class _DomSequence(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.tokens=[]
    def handle_starttag(self, tag, attrs):
        semantic={key:value for key,value in attrs if key in {"role","type","aria-label","aria-labelledby","aria-describedby","aria-live","alt","for","name"}}
        self.tokens.append(f"<{tag}:{sorted(semantic.items())}>")
    def handle_startendtag(self, tag, attrs): self.handle_starttag(tag,attrs)
    def handle_endtag(self, tag): self.tokens.append(f"</{tag}>")

def dom_distance(original, candidate):
    left=_DomSequence(); right=_DomSequence(); left.feed(original); right.feed(candidate)
    similarity=SequenceMatcher(None,left.tokens,right.tokens,autojunk=False).ratio()
    return round((1-similarity)*100,2),len(left.tokens),len(right.tokens)

class _DomInventory(HTMLParser):
    def __init__(self): super().__init__(convert_charrefs=True); self.tags=Counter(); self.accessibility=Counter()
    def handle_starttag(self,tag,attrs):
        self.tags[tag]+=1
        for key,value in attrs:
            if key in {"role","alt","lang","for"} or key.startswith("aria-"):
                self.accessibility[key]+=1
    def handle_startendtag(self,tag,attrs): self.handle_starttag(tag,attrs)

def dom_change_summary(original,candidate):
    before=_DomInventory(); after=_DomInventory(); before.feed(original); after.feed(candidate)
    added=[{"element":key,"count":value} for key,value in sorted((after.tags-before.tags).items()) if value]
    removed=[{"element":key,"count":value} for key,value in sorted((before.tags-after.tags).items()) if value]
    accessibility=[{"attribute":key,"count":value} for key,value in sorted((after.accessibility-before.accessibility).items()) if value]
    return {"elements_added":added,"elements_removed":removed,"accessibility_attributes_added":accessibility}

class _ContentInventory(HTMLParser):
    """Inventory durable page meaning without treating CSS or markup as content."""
    def __init__(self, base_url=None):
        super().__init__(convert_charrefs=True); self.hidden=0; self.words=Counter(); self.links=Counter(); self.images=Counter(); self.base_url=base_url
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag in {"script","style","noscript","svg"}: self.hidden+=1
        if tag == "a":
            href=(values.get("href") or "").strip()
            if href and not href.startswith(("#","javascript:")):
                self.links[urljoin(self.base_url,href) if self.base_url else href]+=1
        if tag == "img":
            from remediation_media_contract import noncontent_pixel
            if noncontent_pixel(values): return
            src=(values.get("src") or values.get("data-src") or values.get("data-original") or "").strip()
            if src and not src.startswith("data:"):
                self.images[urljoin(self.base_url,src) if self.base_url else src]+=1
    def handle_startendtag(self,tag,attrs): self.handle_starttag(tag,attrs)
    def handle_endtag(self,tag):
        if tag in {"script","style","noscript","svg"} and self.hidden: self.hidden-=1
    def handle_data(self,data):
        if not self.hidden: self.words.update(re.findall(r"[\w.-]+",data.casefold()))

def image_asset_identity(url):
    """Recognize size/encoding variants of a static image, preserving content keys.

    This is reference identity, not pixel or visual equivalence. Dynamic image
    endpoints, crop selectors, asset paths and signing/content parameters remain
    distinct. No host or experimental source receives a special case.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not re.search(r"\.(?:jpe?g|png|webp|avif|gif|svg)$", parts.path, re.I):
        return url
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        size = key == 'width' and re.fullmatch(r'[0-9]{1,5}', value) and 0 < int(value) <= 16384
        quality = key == 'quality' and re.fullmatch(r'[0-9]{1,3}', value) and 0 < int(value) <= 100
        encoding = key == 'auto' and value in {'webp', 'avif', 'format', 'compress', 'format,compress'}
        if not (size or quality or encoding):
            query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def image_reference_matches(candidate, reference_urls, base_url):
    """Source assets declared by IMG/CSS, including static size/encoding variants."""
    reference_urls = set(reference_urls)
    inventory = _ContentInventory(base_url)
    inventory.feed(candidate)
    identities = {image_asset_identity(url) for url in inventory.images}
    normalized = absolutize_resources(candidate, base_url)
    soup = BeautifulSoup(normalized, 'html.parser')
    sheets = [node.get_text() for node in soup.select('style')]
    sheets += [node['style'] for node in soup.select('[style]')]
    for sheet in sheets:
        sheet = re.sub(r'/\*.*?\*/', '', sheet, flags=re.S)
        for match in re.finditer(r'url\("((?:\\.|[^"\\])*)"\)', sheet):
            value = re.sub(r'\\(.)', r'\1', match.group(1))
            identities.add(image_asset_identity(value))
    return {url for url in reference_urls if image_asset_identity(url) in identities}


def content_retention(original,candidate,base_url=None,*,image_asset_equivalence=False):
    before=_ContentInventory(base_url); after=_ContentInventory(base_url); before.feed(original); after.feed(candidate)
    word_total=sum(before.words.values()); link_total=sum(before.links.values())
    # Repeated responsive/desktop instances of the same asset are one piece of
    # information. Count unique source URLs so removing duplication is not
    # incorrectly reported as image loss.
    original_image_urls=set(before.images); candidate_image_urls=set(after.images); image_total=len(original_image_urls)
    element_image_urls=set(candidate_image_urls)
    element_matches=set(original_image_urls & element_image_urls)
    if image_asset_equivalence and original_image_urls:
        candidate_image_urls|=image_reference_matches(candidate,original_image_urls,base_url)
        identities={image_asset_identity(url) for url in element_image_urls}
        element_matches={url for url in original_image_urls if image_asset_identity(url) in identities}
    original_destinations=set(before.links); candidate_destinations=set(after.links)
    word_kept=sum((before.words & after.words).values()); link_kept=len(original_destinations & candidate_destinations); image_kept=len(original_image_urls & candidate_image_urls)
    return {
        "text_percent":round(100*word_kept/max(1,word_total),2),
        "links_percent":round(100*link_kept/max(1,len(original_destinations)),2) if original_destinations else 100.0,
        "link_measurement":"unique original destinations; responsive duplicates count once",
        "original_link_destinations":len(original_destinations),"candidate_link_destinations":len(candidate_destinations),
        "images_percent":round(100*image_kept/max(1,image_total),2) if image_total else 100.0,
        "original_words":word_total,"candidate_words":sum(after.words.values()),
        "original_links":link_total,"candidate_links":sum(after.links.values()),
        "original_images":image_total,"candidate_images":len(candidate_image_urls-(element_matches-element_image_urls)),
        "missing_text_examples":[word for word,count in (before.words-after.words).most_common(12) for _ in range(min(count,2))],
        "missing_link_examples":sorted(original_destinations-candidate_destinations)[:12],
        "missing_image_examples":sorted(original_image_urls-candidate_image_urls)[:12],
        **({'image_measurement':'source-image-asset-references-v3; matching static size/encoding variants in IMG or CSS, not visual/semantic equivalence',
            'image_element_percent':round(100*len(element_matches)/max(1,image_total),2),
            'css_image_equivalents':sorted((candidate_image_urls&original_image_urls)-element_matches)}if image_asset_equivalence else{}),
    }

def reconstruction_inventory(source, base_url=None):
    """Extract page meaning and UI anatomy independently from its presentation."""
    soup=BeautifulSoup(source,"html.parser")
    for node in soup.select("script,style,noscript,template,svg"): node.decompose()
    def text(node,limit=500): return " ".join(node.get_text(" ",strip=True).split())[:limit]
    inventory={
        "document_text":soup.get_text(" ",strip=True),
        "reading_order":[{"element":item.name,"text":text(item,10000)} for item in soup.select("h1,h2,h3,h4,h5,h6,p,li,dt,dd,caption,th,td,label,legend,summary") if text(item)],
        "title":text(soup.title) if soup.title else "",
        "language":(soup.html or {}).get("lang") if soup.html else None,
        "headings":[{"level":int(item.name[1]),"text":text(item)} for item in soup.select("h1,h2,h3,h4,h5,h6")[:120]],
        "links":[{"text":text(item,240),"url":urljoin(base_url,item.get("href"))} for item in soup.select("a[href]")],
        "images":[{"url":urljoin(base_url,item.get("src") or item.get("data-src") or ""),"alt":item.get("alt"),"title":item.get("title"),"context":text(item.parent,500)} for item in soup.select("img[src],img[data-src]")],
        "controls":[{"element":item.name,"type":item.get("type"),"name":item.get("name"),"label":item.get("aria-label") or item.get("title") or text(item,180)} for item in soup.select("button,input,select,textarea")],
        "sections":[{"element":item.name,"label":item.get("aria-label") or item.get("id"),"text":text(item,1200)} for item in soup.select("header,nav,main,section,article,aside,footer")[:100]],
        "signals":[item.name for item in soup.find_all(True)[:2000]],
    }
    inventory["forms"]=[{"action":urljoin(base_url,item.get("action") or base_url or ""),"method":item.get("method","get"),"id":item.get("id")} for item in soup.select("form")]
    for control,item in zip(inventory["controls"],soup.select("button,input,select,textarea")):
        label=soup.find("label",attrs={"for":item.get("id")}) if item.get("id") else None
        label=label or item.find_parent("label")
        control.update({"id":item.get("id"),"value":item.get("value"),"required":item.has_attr("required"),"label":text(label) if label else control["label"],"options":[{"value":option.get("value"),"text":text(option)} for option in item.select("option")]})
    # Sliders commonly keep their current/queued images in inline JavaScript or
    # style attributes instead of <img>. They remain acquired evidence, not
    # permission to crawl: expose only URLs already present in the frozen DOM.
    asset_pattern=r'''(?i)(?:https?:)?//[^\s"'<>\\]+?\.(?:png|jpe?g|webp|gif|svg)(?:\?[^\s"'<>\\]*)?'''
    css_assets=re.findall(r'''(?i)url\(\s*["']?([^\s"')]+)''',source)
    inventory["media_assets"]=sorted({urljoin(base_url,item) for item in re.findall(asset_pattern,source)+css_assets if not item.startswith("data:") and re.search(r"(?i)\.(?:png|jpe?g|webp|gif|svg)(?:[?#]|$)",item)})
    classes=" ".join(" ".join(item.get("class") or []) for item in soup.find_all(True)[:2000])
    inventory["signals"].extend(re.findall(r"[a-zA-Z][\w-]+",classes))
    return inventory

def complete_html_response(value):
    value=value.strip()
    value=re.sub(r"^```(?:html)?\s*|\s*```$","",value,flags=re.I)
    match=re.search(r"(?is)(<!doctype\s+html.*|<html\b.*)</html>",value)
    return match.group(0) if match else value

def absolutize_resources(html, base_url):
    """Resolve candidate resources against the acquired page's canonical base URL."""
    if not base_url: return html
    from bs4 import BeautifulSoup
    def resolve(value):
        value=value.strip()
        if not value or value.startswith(("#","data:","mailto:","tel:","javascript:","blob:")): return value
        return urljoin(base_url,value)
    def resolve_srcset(value):
        from resource_srcset import rewrite
        return rewrite(value, resolve)
    # Work on attribute values: rewriting quotes in serialized HTML corrupts
    # inline CSS, and global replacement also alters application script text.
    def resolve_css(css):
        pattern = r'''(?is)url\(\s*(?:"((?:\\.|[^"\\])*)"|'((?:\\.|[^'\\])*)'|((?:\\.|[^)\\])*?))\s*\)'''
        def replacement(match):
            value = next(value for value in match.groups() if value is not None).strip()
            def decode_escape(match):
                token=match.group(1)
                if token in ('\n','\r','\r\n','\f'):return ''
                hexadecimal=re.match(r'[0-9a-fA-F]{1,6}',token)
                if hexadecimal:
                    point=int(hexadecimal.group(),16)
                    return chr(point) if 0<point<=0x10ffff and not 0xd800<=point<=0xdfff else '\ufffd'
                return token
            value=re.sub(r'\\([0-9a-fA-F]{1,6}(?:\r\n|[ \t\r\n\f])?|\r\n|.)',decode_escape,value,flags=re.S)
            resolved = resolve(value).replace('\\', '\\\\').replace('"', '\\"')
            return f'url("{resolved}")'
        return re.sub(pattern, replacement, css)
    soup = BeautifulSoup(html, 'html.parser')
    # The first declared base governs relative resource URLs. Resolve the base
    # itself against the document URL, never against its own resolved value.
    declared_base = soup.find('base', href=True)
    if declared_base and isinstance(declared_base.get('href'), str):
        resolved_base = urljoin(base_url, declared_base['href'])
        if urlparse(resolved_base).scheme in {'http', 'https'}:
            base_url = resolved_base
            declared_base['href'] = resolved_base
    for node in soup.find_all(True):
        if node.name == 'base': continue
        for attr in ('src','href','action','poster','data-src','data-original'):
            if isinstance(node.get(attr), str): node[attr] = resolve(node[attr])
        for attr in ('srcset','data-srcset'):
            if isinstance(node.get(attr), str): node[attr] = resolve_srcset(node[attr])
        if node.name == 'img':
            lazy = node.get('data-src') or node.get('data-original')
            if lazy and (not node.get('src') or node['src'].startswith('data:')):
                node['src'] = lazy
        if isinstance(node.get('style'), str): node['style'] = resolve_css(node['style'])
        if node.name == 'style' and node.string is not None:
            node.string.replace_with(resolve_css(str(node.string)))
    return str(soup)

def document_base_url(source, fallback):
    match=re.search(r'(?i)<base\b[^>]*href\s*=\s*["\']([^"\']+)',source)
    if not match: return fallback
    declared=match.group(1).strip()
    resolved=urljoin(fallback,declared) if fallback else declared
    return resolved if urlparse(resolved).scheme in {"http","https"} else fallback

def compact_html(source, limit=240000):
    """Remove non-remediation payload before applying a final safety limit."""
    source=re.sub(r"(?s)<!--.*?-->","",source)
    source=re.sub(
        r"(?is)<script\b([^>]*)>.*?</script>",
        lambda match: f"<script{match.group(1)}></script>" if re.search(r"(?i)\bsrc\s*=",match.group(1)) else "",
        source,
    )
    source=re.sub(r"(?is)<(style|noscript)\b.*?>.*?</\1>","",source)
    source=re.sub(r"(?is)<svg\b([^>]*)>.*?</svg>",lambda match:f"<svg{match.group(1)}></svg>",source)
    source=re.sub(r">\s+<","><",source)
    source=re.sub(r"[ \t]{2,}"," ",source)
    return source[:limit]

def repair_context(source, axe_evidence, lighthouse_evidence, limit=50000):
    from remediation_patch_context import repair_context as focused_context
    return focused_context(source, axe_evidence, lighthouse_evidence, limit)


def source_style_nonce(soup):
    """Reuse an unambiguous source style nonce without changing its CSP."""
    nonces = {node.get('nonce').strip() for node in soup.select('style[nonce]')
              if node.get('nonce', '').strip()}
    # Rails exposes the captured nonce here even when browser serialization
    # hides nonce attributes. Script nonces alone do not authorize styles.
    nonces.update(node.get('content').strip()
                  for node in soup.select('meta[name="csp-nonce"][content]')
                  if node.get('content', '').strip())
    return next(iter(nonces)) if len(nonces) == 1 else None


def apply_repair_plan(document, plan):
    """Apply a constrained selector-based patch plan to the complete frozen HTML."""
    soup=BeautifulSoup(document,"html.parser"); applied=[]; skipped=[]; unchanged=[]
    operations=plan.get("operations") if isinstance(plan,dict) else None
    for operation in (operations or [])[:60]:
        action=str(operation.get("action") or ""); selector=str(operation.get("selector") or "").strip()
        try: targets=soup.select(selector) if selector else []
        except Exception as error:
            skipped.append({"operation":operation,"reason":f"invalid selector: {error}"}); continue
        if action in {"append_css","append_head_html","append_body_html"}:
            targets=[soup]
        if not targets:
            skipped.append({"operation":operation,"reason":"selector did not match"}); continue
        try:
            if action in {'replace_element','insert_before','insert_after','append_head_html','append_body_html'}:
                markup=str(operation.get('html') or '')
                if re.search(r"(?is)<\s*(script|style)\b|\son[a-z]+\s*=|javascript\s*:",markup):
                    raise ValueError('executable markup is forbidden; use scoped CSS/behavior operations')
                if action!='replace_element' and BeautifulSoup(markup,'html.parser').select('main,[role="main"]'):
                    raise ValueError('inserting a new main does not wrap existing content; use a substantive existing container, never a main placeholder')
            if action == "set_attribute":
                name=str(operation.get("name") or "").strip(); value=str(operation.get("value") or "")
                if not name or re.search(r"[^a-zA-Z0-9_:-]",name): raise ValueError("invalid attribute")
                if name.lower()=="role" and value.lower()=="presentation" and any(target.name=="li" for target in targets):
                    raise ValueError("role=presentation cannot repair an orphan list item; restore list structure")
                if name.lower()=="role" and value.lower()=="main":
                    if any(target.name=="body" or (not target.get_text(" ",strip=True) and len(target.find_all(True))<2) for target in targets):
                        raise ValueError("main landmark must be a substantive page-content container, never body or an empty placeholder")
                if all(target.get(name) == value for target in targets):
                    unchanged.append(operation)
                    continue
                for target in targets: target[name]=value
            elif action == "remove_attribute":
                name=str(operation.get("name") or "").strip()
                if all(name not in target.attrs for target in targets):
                    unchanged.append(operation)
                    continue
                for target in targets: target.attrs.pop(name,None)
            elif action == 'remove_decorative_image':
                from remediation_decorative_resource import removable
                if not all(removable(target) for target in targets):
                    raise ValueError('decorative image removal requires empty one-pixel images and independent control names')
                for target in targets:target.decompose()
            elif action == "replace_element":
                if selector.lower() in {"html","head","body"}: raise ValueError("root replacement is forbidden")
                raw_markup=str(operation.get("html") or "")
                replacement=BeautifulSoup(raw_markup,"html.parser")
                if not replacement.contents: raise ValueError("empty replacement")
                for target in targets: target.replace_with(BeautifulSoup(str(replacement),"html.parser"))
            elif action == 'wrap_element':
                tag=operation.get('tag')
                if tag not in {'ul','ol'} or any(target.name!='li' for target in targets):
                    raise ValueError('list repair wraps only li elements in ul/ol')
                for target in targets:
                    if target.parent.name in {'ul','ol'}: continue
                    wrapper=soup.new_tag(tag)
                    parent=target.parent
                    navigation_classes={'nav','navbar-nav','pagination','breadcrumb'}
                    if parent.name=='nav' or target.find_parent('nav') or navigation_classes.intersection(parent.get('class') or []):
                        # A native wrapper must not introduce browser-default
                        # bullets/padding into an originally unbulleted menu.
                        # Explicit list semantics survive list-style:none.
                        wrapper['role']='list'
                        wrapper['data-warp-navigation-list']='true'
                        wrapper['style']='list-style: none; margin: 0; padding: 0;'
                    target.wrap(wrapper)
            elif action in {"insert_before","insert_after"}:
                markup=str(operation.get("html") or "")
                for target in targets:
                    fragment=BeautifulSoup(markup,"html.parser")
                    target.insert_before(fragment) if action=="insert_before" else target.insert_after(fragment)
            elif action == "append_css":
                css = str(operation.get('css') or '')[:30000]
                if any(style.get_text().strip() == css.strip() for style in soup.select('style')):
                    unchanged.append(operation)
                    continue
                style = soup.new_tag('style')
                style['data-warp-repair'] = 'true'
                nonce = source_style_nonce(soup)
                if nonce:
                    style['nonce'] = nonce
                style.string = css
                insert_head_metadata(soup,style)
            elif action == "append_javascript":
                javascript=str(operation.get("javascript") or "")
                if re.search(r"\b(fetch|XMLHttpRequest|eval|Function|localStorage|sessionStorage)\b|document\.(cookie|write)|(?:window\.)?location\s*=",javascript):
                    raise ValueError("behavior repair must be local; navigation/network/storage/dynamic execution forbidden")
                script=soup.new_tag("script"); script["data-warp-repair"]="true"; script.string=javascript[:30000]
                (soup.body or soup).append(script)
            elif action in {"append_head_html","append_body_html"}:
                markup=str(operation.get("html") or "")
                destination=soup.head if action=="append_head_html" else soup.body
                if destination is None: raise ValueError("document section missing")
                if action=='append_head_html':insert_head_markup(soup,markup)
                else:destination.append(BeautifulSoup(markup,'html.parser'))
            else: raise ValueError("unsupported action")
            applied.append(operation)
        except Exception as error: skipped.append({"operation":operation,"reason":str(error)})
    return str(soup),{"applied":applied,"skipped":skipped,"unchanged":unchanged}


def lighthouse_failure_evidence(raw_path, limit=8):
    """Return only actionable failed Lighthouse accessibility audits."""
    path=Path(raw_path or "")
    if not path.is_file(): return []
    try: audits=(json.loads(path.read_text(encoding="utf-8")) or {}).get("audits") or {}
    except (OSError,ValueError,TypeError): return []
    failures=[]
    for audit_id,audit in audits.items():
        score=audit.get("score")
        if audit.get("scoreDisplayMode") in {"notApplicable","manual","informative"} or score is None or score >= 1: continue
        items=((audit.get("details") or {}).get("items") or [])[:4]
        failures.append({"audit":audit_id,"title":audit.get("title"),"description":audit.get("description"),"score":score,"items":[{"selector":item.get("node",{}).get("selector"),"snippet":item.get("node",{}).get("snippet"),"explanation":item.get("node",{}).get("explanation")} for item in items]})
    failures.sort(key=lambda item:(item["score"],item["audit"]))
    return failures[:limit]


def axe_failure_evidence(raw_path, limit=8):
    path=Path(raw_path or "")
    if not path.is_file(): return []
    try: violations=json.loads(path.read_text(encoding="utf-8"))["violations"]
    except (OSError,ValueError,KeyError,TypeError): return []
    evidence=[]
    violations = [entry for entry in violations if 'best-practice' not in entry.get('tags', [])]
    for violation in violations[:limit]:
        nodes=[]
        for node in violation.get("nodes",[])[:4]:
            nodes.append({"target":node.get("target"),"html":str(node.get("html") or "")[:500],"failure":str(node.get("failureSummary") or "")[:500],"computed_style":node.get('computed_style'),"ancestor_styles":node.get('ancestor_styles')})
        evidence.append({"rule":violation.get("id"),"impact":violation.get("impact"),"help":violation.get("help"),"nodes":nodes})
    return evidence
