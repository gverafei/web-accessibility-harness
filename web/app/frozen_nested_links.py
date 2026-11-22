"""Preserve browser-created nested anchors across captured-DOM serialization."""
import hashlib
import json
from pathlib import Path

VERSION = 'captured-nested-links-v1'
RUNTIME = Path(__file__).with_suffix('.js')
MARKER = 'data-warp-frozen-nested-anchor'
LINK_ATTRIBUTES = ('href', 'target', 'download', 'ping', 'rel', 'hreflang',
                   'type', 'referrerpolicy')


def prepare_nested_links(soup):
    evidence = []
    runtime = RUNTIME.read_text(encoding='utf-8')
    for anchor in list(soup.select('a a')):
        if not anchor.has_attr('href'):
            continue
        attributes = {}
        for key in LINK_ATTRIBUTES:
            if anchor.has_attr(key):
                value = anchor.attrs.pop(key)
                attributes[key] = ' '.join(value) if isinstance(value, list) else str(value)
        anchor.name = 'span'
        anchor[MARKER] = json.dumps(attributes, ensure_ascii=False, separators=(',', ':'))
        evidence.append({'component': 'captured-nested-links', 'version': VERSION,
                         'runtime_sha256': hashlib.sha256(runtime.encode()).hexdigest(),
                         'method': 'Restore acquired anchor topology after HTML parsing; no repair or navigation'})
    if evidence and not soup.select('script[data-warp-frozen-nested-links-runtime]'):
        helper = soup.new_tag('script')
        helper['data-warp-frozen-nested-links-runtime'] = VERSION
        nonce = soup.select_one('script[nonce]')
        if nonce:
            helper['nonce'] = nonce['nonce']
        helper.string = runtime
        (soup.head or soup).insert(0, helper)
    return evidence
