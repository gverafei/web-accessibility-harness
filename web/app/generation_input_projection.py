"""Shorten repeated CSS evidence while retaining content and the final cascade."""
import hashlib
import json

from bs4 import BeautifulSoup


def compact_asset_catalog(urls):
    """Encode every URL as a base/query pair, preserving its exact bytes and order."""
    bases, suffixes, references = [], [], []
    base_indexes, suffix_indexes = {}, {}
    for url in urls:
        base, separator, query = url.partition('?')
        suffix = separator + query
        if base not in base_indexes:
            base_indexes[base] = len(bases)
            bases.append(base)
        if suffix not in suffix_indexes:
            suffix_indexes[suffix] = len(suffixes)
            suffixes.append(suffix)
        references.append([base_indexes[base], suffix_indexes[suffix]])
    catalog = {'version': 'exact-asset-url-catalog-v1', 'bases': bases,
               'suffixes': suffixes, 'references': references,
               'decode': 'For each [i,j], concatenate bases[i] + suffixes[j] to obtain the exact original URL.'}
    assert [bases[i] + suffixes[j] for i, j in references] == urls
    if len(json.dumps(catalog)) >= len(json.dumps(urls)):
        return None
    return catalog


def compact_repeated_styles(source):
    soup = BeautifulSoup(source, 'html.parser')
    seen = set()
    removed = 0
    for node in reversed(soup.find_all('style')):
        # Template/shadow scopes and observable stylesheet identities stay intact.
        if node.find_parent('template') or any(key in node.attrs for key in (
                'id', 'scoped', 'title', 'disabled')):
            continue
        css = node.get_text()
        key = (css, json.dumps(node.attrs, sort_keys=True))
        if not css or key not in seen:
            seen.add(key)
            continue
        node.string = ''
        removed += 1
    projected = str(soup) if removed else source
    return projected, {
        'version': 'repeated-style-input-projection-v1',
        'original_sha256': hashlib.sha256(source.encode()).hexdigest(),
        'projected_sha256': hashlib.sha256(projected.encode()).hexdigest(),
        'original_bytes': len(source.encode()), 'projected_bytes': len(projected.encode()),
        'duplicate_style_bodies': removed,
        'scope': 'Generation input only; original acquisition and reference remain unchanged',
    }
