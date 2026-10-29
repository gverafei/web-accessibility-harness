"""Restore exact recorded CSS, image variants and consent state for local replay."""
import hashlib
from urllib.parse import urlsplit

def saved_consent_controls(source):
    """Restore explicit local dismissal for an observed, frozen Iubenda banner.

    Serialized initialized DOM keeps the buttons but not their event listeners.
    This transport adapter changes only the local banner after a user action;
    it neither sends consent to the publisher nor edits canonical audit inputs.
    """
    from bs4 import BeautifulSoup
    marker = 'data-harness-local-consent'
    if marker in source:
        return (source, [])
    soup = BeautifulSoup(source, 'html.parser')
    banner = soup.select_one('#iubenda-cs-banner')
    frozen_boot = soup.select_one('script[data-warp-frozen-acquired-boot]')
    if banner is None or frozen_boot is None:
        return (source, [])
    if not all((banner.select_one('.iubenda-cs-' + choice + '-btn') for choice in ('accept', 'reject'))):
        return (source, [])
    adapter = '<script data-harness-local-consent="observed-iubenda-v1">\ndocument.addEventListener(\'click\', function (event) {\n    const button = event.target.closest(\'.iubenda-cs-accept-btn, .iubenda-cs-reject-btn\');\n    const banner = button && button.closest(\'#iubenda-cs-banner\');\n    if (!banner) return;\n    event.preventDefault();\n    event.stopImmediatePropagation();\n    banner.dataset.harnessLocalChoice = button.classList.contains(\'iubenda-cs-accept-btn\') ? \'accept\' : \'reject\';\n    banner.style.setProperty(\'display\', \'none\', \'important\');\n    banner.setAttribute(\'hidden\', \'\');\n}, true);\n</script>'
    return (source + adapter, [{'component': 'observed-iubenda-banner', 'version': 'observed-iubenda-v1', 'controls': ['accept', 'reject'], 'scope': 'Local dismissal only; no publisher consent request or cookie write.'}])

def saved_stylesheet_references(source, capture):
    """Match only browser-equivalent stylesheet requests to captured CSS bytes."""
    from html.parser import HTMLParser
    from urllib.parse import urljoin, urlsplit, urlunsplit, quote
    from bs4 import BeautifulSoup
    origin = capture['data']['captured_url']

    def request_key(url):
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if parts.scheme not in ('http', 'https') or not parts.hostname:
            return None
        path = quote(parts.path, safe="/:@-._~!$&'()*+,;=%")
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ''))
    groups = {}
    exact = set()
    for asset in capture['data'].get('assets', []):
        if asset.get('mime', '').split(';')[0] != 'text/css' or asset.get('http_status', 200) != 200:
            continue
        exact.add(asset['url'])
        key = request_key(asset['url'])
        if key is not None:
            groups.setdefault(key, []).append(asset)
    if not groups:
        return (source, [])
    offsets = [0] + [index + 1 for index, char in enumerate(source) if char == '\n']
    replacements, changes = ([], [])

    class Stylesheets(HTMLParser):

        def handle_starttag(self, tag, attributes):
            attrs = dict(attributes)
            if tag != 'link' or 'stylesheet' not in (attrs.get('rel') or '').lower().split():
                return
            value = attrs.get('href')
            if not value:
                return
            try:
                absolute = urljoin(origin, value)
            except ValueError:
                return
            if absolute in exact:
                return
            matches = groups.get(request_key(absolute), [])
            if not matches or len({a['sha256'] for a in matches}) != 1:
                return
            captured = matches[-1]['url']
            raw = self.get_starttag_text()
            line, column = self.getpos()
            start = offsets[line - 1] + column
            if source[start:start + len(raw)] != raw:
                return
            node = BeautifulSoup(raw, 'html.parser').find('link')
            node['href'] = captured
            replacements.append((start, start + len(raw), str(node)))
            changes.append({'original': value, 'navigation': captured, 'sha256': matches[-1]['sha256'], 'reason': 'Same captured CSS request after URL path encoding and network-fragment omission; query parameters unchanged.'})
    Stylesheets(convert_charrefs=False).feed(source)
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    return (source, changes)

def saved_image_variants(source, capture):
    """Use saved img/picture variants in the derived navigation copy only.

    The captured source, frozen acquisition runtime and audit inputs stay intact.
    Unavailable images remain unavailable; no replacement content is inferred.
    Only changed opening tags are serialized, preserving all other source bytes.
    """
    from html.parser import HTMLParser
    from urllib.parse import urljoin, urlsplit, parse_qs
    from bs4 import BeautifulSoup
    from resource_srcset import candidates
    from .html_tools import image_asset_identity
    origin = capture['data']['captured_url']
    saved = {asset['url'] for asset in capture['data'].get('assets', [])}
    image_variants = {}
    for asset in capture['data'].get('assets', []):
        if asset.get('mime', '').split(';')[0].startswith('image/') and asset.get('http_status', 200) == 200 and (asset.get('sha256') != hashlib.sha256(b'').hexdigest()):
            image_variants.setdefault(image_asset_identity(asset['url']), set()).add(asset['url'])

    def variant_priority(url):
        params = parse_qs(urlsplit(url).query)
        width = params.get('width', ['0'])[0]
        return (-int(width) if width.isdigit() else 0, url)
    variants = {key: min(urls, key=variant_priority) for key, urls in image_variants.items()}
    resolutions = {}

    def resolve(url):
        if not url:
            return None
        if url.startswith('data:'):
            return url
        absolute = urljoin(origin, url)
        if absolute in saved:
            return url
        if absolute not in resolutions:
            resolutions[absolute] = variants.get(image_asset_identity(absolute))
        return resolutions[absolute]
    offsets = [0] + [index + 1 for index, char in enumerate(source) if char == '\n']
    changes, replacements = ([], [])

    def available(url):
        return resolve(url) is not None

    class Images(HTMLParser):

        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.pictures = []

        def handle_starttag(self, tag, attributes):
            tag = tag.lower()
            if tag == 'picture':
                self.pictures.append({'sources': [], 'fallback': False})
                return
            if tag not in ('img', 'source'):
                return
            raw = self.get_starttag_text()
            line, column = self.getpos()
            start = offsets[line - 1] + column
            if source[start:start + len(raw)] != raw:
                return
            if tag == 'source':
                if self.pictures:
                    self.pictures[-1]['sources'].append((tag, raw, attributes, start))
                return
            attrs = dict(attributes)
            if self.pictures:
                self.pictures[-1]['fallback'] |= available(attrs.get('src', '')) or any((available(url) for url, _ in candidates(attrs.get('srcset', ''))))
            self.adjust(tag, raw, attributes, start, available(attrs.get('src', '')))

        def handle_endtag(self, tag):
            if tag.lower() == 'picture' and self.pictures:
                picture = self.pictures.pop()
                for args in picture['sources']:
                    self.adjust(*args, picture['fallback'])

        def adjust(self, tag, raw, attributes, start, fallback):
            node = None
            if tag == 'img':
                for attr, value in attributes:
                    if attr not in ('src', 'data-src', 'data-original'):
                        continue
                    replacement = resolve(value)
                    if replacement and replacement != value:
                        if node is None:
                            node = BeautifulSoup(raw, 'html.parser').find(tag)
                        node[attr] = replacement
                        changes.append({'element': tag, 'attribute': attr, 'original': value, 'navigation': replacement, 'reason': 'Saved size/encoding variant of the same static image; content, crop and signed parameters stay distinct.'})
            for attr, value in attributes:
                if attr not in ('srcset', 'data-srcset') or not value or 'data:' in value.lower():
                    continue
                options = list(candidates(value))
                retained = [(resolve(url), descriptor) for url, descriptor in options if available(url)]
                if retained == options:
                    continue
                if not retained and (not fallback):
                    continue
                if node is None:
                    node = BeautifulSoup(raw, 'html.parser').find(tag)
                if retained:
                    node[attr] = ', '.join(((url + ' ' + descriptor).rstrip() for url, descriptor in retained))
                else:
                    node.attrs.pop(attr, None)
                changes.append({'element': tag, 'attribute': attr, 'original': value, 'navigation': node.get(attr), 'reason': 'Only captured variants of this same image are selectable.'})
            if node is not None:
                replacements.append((start, start + len(raw), str(node)))
    parser = Images()
    parser.feed(source)
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    return (source, changes)
