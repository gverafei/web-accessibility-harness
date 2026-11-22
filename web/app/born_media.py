"""Shared readability metadata; no component replacement or resource rewriting."""
import re
from urllib.parse import urlparse

FOOTER_MEDIA_CSS='''img[data-warp-icon]{width:1.75rem!important;height:1.75rem!important;object-fit:contain;vertical-align:middle}
img[data-warp-brand]{width:min(100%,22rem);height:auto}
footer a:has(img[data-warp-icon]){display:inline-flex;align-items:center;gap:.5rem;padding:.5rem}'''


def mark_footer_media(soup):
    for image in soup.select('img'):
        filename=urlparse(image.get('src','')).path.rsplit('/',1)[-1].casefold()
        alternative=image.get('alt','').casefold()
        if image.find_parent('a') and (re.match(r'(?:ico[-_]|icons?[-_\d])',filename) or alternative in {'linkedin','facebook','instagram','rss','external link icon'}):
            image['data-warp-icon']='true'
        elif 'logo' in alternative:
            image['data-warp-brand']='true'
