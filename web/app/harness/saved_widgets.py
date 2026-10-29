"""Bind recorded Bootstrap disclosures and initialized Slick widgets in saved copies."""
from urllib.parse import urljoin

BOOTSTRAP = '9520018fa5d81f4e4dc9d06afb576f90cbbaba209cfcc6cb60e1464647f7890b'
SLICK = '4f183d6af3e88171a4bbae9a2e77f90f55b425b013d057b80eade59f96ae5d0d'
GLOBAL = 'e67170f55b8397f36a7002da3cf5ac13c7256cb10872ed0a2aa9c86c20f77341'
HOME = 'bd44ecb1307718a83c60355fc941984adca3cee5a4cc21392ce9aaa96d5aa409'
SLICK_19 = '357452f2a55c999ddd3afdcbce2c339d41cf7a01613d9d45ff88a753bb82f21d'
NEWS_FEED = 'c9e7c110e63dc1379a609ab18ba5741e86d2ae614ee30194d26d65916e19a6a7'


def bound(soup, capture, sha256):
    urls = {a['url'] for a in capture['data'].get('assets', []) if a.get('sha256') == sha256}
    return any(urljoin(capture['data'].get('captured_url', ''), n.get('src', '')) in urls
               for n in soup.select('script[data-warp-frozen-acquired-boot][src]'))


def prepare(soup, capture, element_path):
    result = []
    if bound(soup, capture, BOOTSTRAP):
        for toggle in soup.select('[data-bs-toggle="dropdown"]'):
            menus = toggle.parent.find_all(class_='dropdown-menu', recursive=False)
            triggers = toggle.parent.find_all(attrs={'data-bs-toggle':'dropdown'}, recursive=False)
            ident = toggle.get('id')
            if (toggle.name not in ('a','button') or len(triggers) != 1 or len(menus) != 1
                    or (ident and len(soup.find_all(id=ident)) != 1)
                    or (menus[0].get('aria-labelledby') and menus[0]['aria-labelledby'] != ident)
                    or not menus[0].select('a[href], input, form')):
                continue
            result.append({'kind': 'dropdown', 'trigger': element_path(toggle),
                           'panel': element_path(menus[0]), 'binding_sha256': BOOTSTRAP})
        for toggle in soup.select('[data-bs-toggle="collapse"][aria-controls]'):
            target = toggle.get('data-bs-target') or toggle.get('href')
            panels = soup.find_all(id=toggle['aria-controls'])
            if (target != '#' + toggle['aria-controls'] or len(panels) != 1
                    or 'collapse' not in panels[0].get('class', [])):
                continue
            result.append({'kind': 'collapse', 'trigger': element_path(toggle),
                           'panel': element_path(panels[0]), 'binding_sha256': BOOTSTRAP})
    # Options are from these exact saved publisher functions, not inferred by domain.
    if all(bound(soup, capture, value) for value in (SLICK, GLOBAL, HOME)):
        binding = [SLICK, GLOBAL, HOME]
        profiles = [('.noticias-slider', 1, 1, []),
                    ('.agenda-deck', 3, 3, [[992, 2, 2], [768, 1, 1]]),
                    ('.testimonios-deck', 2, 1, [[992, 1, 1]]),
                    ('.numeralia .card-deck', 4, 4, [[992, 2, 2], [768, 1, 1]]),
                    ('.regiones-deck', 5, 1, [[1200, 3, 3], [992, 2, 2], [768, 1, 1]])]
    elif all(bound(soup, capture, value) for value in (SLICK_19, GLOBAL, NEWS_FEED)):
        binding = [SLICK_19, GLOBAL, NEWS_FEED]
        profiles = [('.noticias-slider', 1, 1, [])]
    else:
        return result
    for selector, show, step, responsive in profiles:
        roots = soup.select(selector + '.slick-initialized')
        if len(roots) != 1:
            continue
        root = roots[0]
        lists = root.find_all(class_='slick-list', recursive=False)
        tracks = lists[0].find_all(class_='slick-track', recursive=False) if len(lists) == 1 else []
        slides = tracks[0].find_all(recursive=False) if len(tracks) == 1 else []
        if (not slides or any('slick-slide' not in n.get('class', [])
                or 'slick-cloned' in n.get('class', []) or n.get('data-slick-index') != str(i)
                for i, n in enumerate(slides))):
            continue
        current = [i for i, n in enumerate(slides) if 'slick-current' in n.get('class', [])]
        if len(current) != 1:
            continue
        result.append({'kind': 'slick', 'root': element_path(root), 'count': len(slides),
                       'active': current[0], 'show': min(show, len(slides)), 'step': step,
                       'responsive': responsive, 'binding_sha256': binding})
    return result
