"""Restore recorded presentation state in derived saved-page copies."""
import json
import hashlib
import math
import re
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup

VERSION = 'observed-review-presentation-v6'
RUNTIME = Path(__file__).parents[1] / 'static/js/observed_state.js'


def presentation_signature():
    """Invalidate display copies when local bindings change, without changing evidence."""
    files = [Path(__file__), Path(__file__).with_name('saved_widgets.py'),
             Path(__file__).with_name('saved_navigation.py'), RUNTIME,
             RUNTIME.with_name('saved_widgets.js'), RUNTIME.with_name('saved_navigation.js')]
    return hashlib.sha256(b'\0'.join(path.read_bytes() for path in files)).hexdigest()


def element_path(element):
    parts = []
    while element and element.name != 'html':
        parent = element.parent
        if parent is None:
            return None
        peers = parent.find_all(element.name, recursive=False)
        position = next(index for index, peer in enumerate(peers, 1) if peer is element)
        parts.insert(0, f'{element.name}:nth-of-type({position})')
        element = parent
    return 'html > ' + ' > '.join(parts) if element else None


def paused_media(soup, capture):
    """Select exact observed videos with complete, unambiguous saved bytes."""
    from .saved_navigation import BOOTSTRAP_SHA256
    data = capture['data']
    saved = {}
    for asset in data.get('assets', []):
        if (asset.get('mime', '').startswith('video/') and asset.get('http_status') == 200
                and asset.get('media_capture', {}).get('complete') is True
                and re.fullmatch(r'[a-f0-9]{64}', asset.get('sha256', ''))):
            saved.setdefault(asset['url'], set()).add(asset['sha256'])
    result = []
    for reference in data.get('visible', {}).get('media_descriptors', []):
        if not isinstance(reference, dict):
            continue
        path, time = reference.get('position_path'), reference.get('current_time')
        if (reference.get('position_version') != 'observed-media-position-v1'
                or reference.get('state') != 'loaded' or reference.get('paused') is not True
                or type(time) not in (int, float) or not math.isfinite(time) or not 0 <= time <= 86400
                or not isinstance(path, str)
                or not re.fullmatch(r'html(?: > [a-z][a-z0-9-]*:nth-of-type\([1-9]\d*\))+', path)):
            continue
        nodes = soup.select(path)
        src = reference.get('src_attribute')
        sources = reference.get('source_attributes', [])
        matches = saved.get(reference.get('current_src'), set())
        if len(nodes) != 1 or nodes[0].name != 'video' or len(matches) != 1:
            continue
        node = nodes[0]
        if src:
            valid = node.get('src') == src and not node.find('source')
        else:
            children = node.find_all('source', recursive=False)
            valid = (not node.get('src') and len(children) == 1 and len(sources) == 1
                     and children[0].get('src') == sources[0])
            src = sources[0] if valid else None
        if not valid or urljoin(data.get('captured_url', ''), src) != reference.get('current_src'):
            continue
        result.append({'path': path, 'time': time, 'sha256': next(iter(matches)),
                       'width': reference.get('video_width'), 'height': reference.get('video_height')})
        # The saved hero module defines this exact play/pause binding. Do not boot it.
        if any(a.get('sha256') == BOOTSTRAP_SHA256 for a in data.get('assets', [])):
            hero = node.find_parent(class_='b-hero')
            buttons = hero.select('button[data-js="video-trigger"]') if hero else []
            if len(buttons) == 1 and len(hero.select('video.b-hero__bg-video')) == 1:
                result[-1]['control'] = element_path(buttons[0])
                result[-1]['binding_sha256'] = BOOTSTRAP_SHA256
    return [item for item in result if sum(other['path'] == item['path'] for other in result) == 1]


def prepare(source, capture):
    """Append a local adapter without changing any recorded document bytes."""
    if 'data-harness-observed-state=' in source or 'data-warp-frozen-acquired-boot' not in source:
        return source, []
    soup = BeautifulSoup(source, 'html.parser')
    if not soup.select_one('script[data-warp-frozen-acquired-boot]'):
        return source, []
    references = capture['data'].get('visible', {}).get('animation_reference', [])
    animations = [r for r in references if isinstance(r, dict)
                  and r.get('version') == 'observed-css-animation-state-v1']
    media = paused_media(soup, capture)
    from .saved_navigation import prepare as navigation_controls
    navigation = navigation_controls(soup, capture, element_path)
    from .saved_widgets import prepare as saved_widgets
    widgets = saved_widgets(soup, capture, element_path)
    carousels = []
    # Embla Fade serializes a single active, full-width slide and pixel offsets.
    # Require its recorded initialization, not merely a carousel-looking class.
    for viewport in soup.select('[x-ref="embla"]'):
        if 'EmblaFade' not in viewport.get('wire:effects', ''):
            continue
        track = viewport.find('div', recursive=False)
        slides = track.find_all(recursive=False) if track else []
        if len(slides) < 2 or any('flex-[0_0_100%]' not in slide.get('class', []) for slide in slides):
            continue
        active = []
        valid = True
        for index, slide in enumerate(slides):
            style = dict((key.strip(), value.strip()) for key, value in
                         re.findall(r'([\w-]+)\s*:\s*([^;]+)', slide.get('style', '')))
            if (style.get('opacity') not in ('0', '1')
                    or not re.fullmatch(r'translateX\(-?[\d.]+px\)', style.get('transform', ''))
                    or style.get('pointer-events') != ('auto' if style['opacity'] == '1' else 'none')):
                valid = False
                break
            if style['opacity'] == '1':
                active.append(index)
        path = element_path(track)
        if valid and len(active) == 1 and path:
            controls = []
            for button in viewport.select('button'):
                if button.find_parent(attrs={'x-ref': 'embla'}) is not viewport:
                    continue
                action = button.get('@click', '')
                match = re.fullmatch(r'emblaCarousel\.scrollTo\((\d+)\)', action)
                if match and int(match[1]) < len(slides):
                    controls.append({'path': element_path(button), 'index': int(match[1]), 'action': action})
            carousels.append({'path': path, 'count': len(slides), 'active': active[0], 'controls': controls})
    if not animations and not carousels and not media and not navigation and not widgets:
        return source, []
    payload = json.dumps({'animations': animations, 'carousels': carousels, 'media': media,
                          'navigation': navigation, 'widgets': widgets},
                         ensure_ascii=True).replace('<', '\\u003c')
    adapter = (f'\n<script type="application/json" data-harness-observed-state="{VERSION}">'
               + payload + '</script>\n<script>\n' + RUNTIME.read_text()
               + '\n' + (RUNTIME.parent / 'saved_navigation.js').read_text() + '\n' + (RUNTIME.parent / 'saved_widgets.js').read_text()
               + '\n</script>')
    return source + adapter, [{'version': VERSION, 'animation_references': len(animations),
        'responsive_fade_carousels': len(carousels),
        'local_slide_controls': sum(len(c['controls']) for c in carousels),
        'paused_saved_videos': len(media),
        'saved_navigation_bindings': navigation,
        'saved_widget_bindings': widgets,
        'scope': 'Recorded CSS effects, saved slide/menu navigation and paused complete saved videos only; no publisher boot, external requests or audit changes.'}]
