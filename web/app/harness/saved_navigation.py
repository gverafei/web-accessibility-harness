"""Recognize one captured disclosure contract without running publisher code."""
from urllib.parse import urljoin

NAVIGATION_SHA256 = 'c944a9e17a7f5b32a52eaab8ffafa992c6e7cd8bd9563a5cc4d6ba78f4f0d8ba'
STYLESHEET_SHA256 = '0e203130cf01c6710373046614ae8356614e5f4bd7bef03c5f38a7bbcf1e79d9'
BOOTSTRAP_SHA256 = 'fdf88d0ffda34c9202f164105f2965d3d30b2f3ffe773c9bc78a8abce0096132'


def prepare(soup, capture, element_path):
    data = capture['data']
    assets = data.get('assets', [])
    urls = {a['url'] for a in assets if a.get('sha256') == BOOTSTRAP_SHA256}
    if (not urls or not any(a.get('sha256') == NAVIGATION_SHA256 for a in assets)
            or not any(a.get('sha256') == STYLESHEET_SHA256 for a in assets)
            or not any(urljoin(data.get('captured_url', ''), n.get('src', '')) in urls
                       for n in soup.select('script[data-warp-frozen-acquired-boot][src]'))):
        return []
    panels = soup.select('[data-js="site-nav"][id="site-nav"][aria-hidden]')
    opens = soup.select('button[data-js="site-trigger-nav-open"][aria-controls="site-nav"]')
    closes = soup.select('button[data-js="site-trigger-nav-close"][aria-controls="site-nav"]')
    headers = soup.select('[data-js="site-header"]')
    if any(len(nodes) != 1 for nodes in (panels, opens, closes, headers)):
        return []
    panel = panels[0]
    nav = panel.select('[data-js="site-nav-container"]')
    if len(nav) != 1 or not panel.select('a[href]'):
        return []
    children = []
    for button in nav[0].select('button[data-js="trigger-child-menu"][aria-controls]'):
        matches = soup.find_all(id=button['aria-controls'])
        if len(matches) != 1:
            continue
        child = matches[0]
        backs = [n for n in child.select('button[data-js="trigger-menu-return"]')
                 if n.get('aria-controls') == child.get('id')]
        if (child not in button.parent.find_all('div') or len(backs) != 1
                or child.get('aria-labelledby') != button.get('id')
                or backs[0].get('aria-controls') != child.get('id')
                or button.get('data-depth') not in ('0', '1')):
            continue
        children.append({'trigger': element_path(button), 'panel': element_path(child),
                         'back': element_path(backs[0]), 'depth': int(button['data-depth'])})
    return [{'panel': element_path(panel), 'header': element_path(headers[0]),
             'nav': element_path(nav[0]), 'open': element_path(opens[0]),
             'close': element_path(closes[0]), 'children': children,
             'binding_sha256': NAVIGATION_SHA256, 'stylesheet_sha256': STYLESHEET_SHA256}]
