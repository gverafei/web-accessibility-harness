"""Bounded, library-specific captured-widget replay; never domain-specific."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from bs4 import BeautifulSoup

VERSION = 'slick-frozen-replay-v1'
RUNTIME = Path(__file__).with_suffix('.js')


def _content(slide):
    if set(slide.attrs) - {'class','data-slick-index','role','id','aria-hidden','aria-describedby','tabindex','style'}:
        return None
    if slide.get('role') not in {None, 'tabpanel'}:
        return None
    children = slide.find_all(True, recursive=False)
    if len(children) != 1 or children[0].name != 'div':
        return None
    wrapper = children[0]
    if set(wrapper.attrs) - {'style'}:
        return None  # Do not discard authored semantics or a patch on a wrapper.
    parts = wrapper.find_all(True, recursive=False)
    if len(parts) != 1:
        return None
    return parts[0]


def prepare_carousels(soup):
    """Dehydrate only proven Slick wrappers; retain slide content and controls."""
    library = any(re.search(r'/slick(?:\.min)?\.js$', urlsplit(node.get('src', '')).path, re.I)
                  for node in soup.select('script[src]'))
    if not library:
        return []
    evidence = []
    runtime = RUNTIME.read_text(encoding='utf-8')
    digest = hashlib.sha256(runtime.encode()).hexdigest()
    for index, root in enumerate(soup.select('.slick-initialized')):
        if root.has_attr('data-warp-frozen-slick'):
            continue
        lists = root.find_all(class_='slick-list', recursive=False)
        if len(lists) != 1:
            continue
        tracks = lists[0].find_all(class_='slick-track', recursive=False)
        if len(tracks) != 1 or len(lists[0].find_all(True, recursive=False)) != 1:
            continue
        slides = tracks[0].find_all(True, recursive=False)
        if not slides or any('slick-slide' not in slide.get('class', []) or _content(slide) is None for slide in slides):
            continue
        originals = [slide for slide in slides if 'slick-cloned' not in slide.get('class', [])]
        if not originals or len({slide.get('data-slick-index') for slide in originals}) != len(originals):
            continue
        original_content = {str(_content(slide)) for slide in originals}
        if any(str(_content(slide)) not in original_content for slide in slides if slide not in originals):
            continue  # A non-identical clone may contain unique content or a repair.
        extras = [child for child in root.find_all(True, recursive=False) if child is not lists[0]]
        if any(not set(child.get('class', [])) & {'slick-prev', 'slick-next', 'slick-dots'} for child in extras):
            continue
        try:
            declared = json.loads(root.get('data-slick') or '{}')
            if not isinstance(declared, dict):
                continue
        except (ValueError, TypeError):
            continue
        # Only bounded presentational options from observed capture state.
        options = {key: value for key, value in declared.items() if key in {
            'autoplay', 'autoplaySpeed', 'speed', 'slidesToShow', 'slidesToScroll',
            'vertical', 'verticalSwiping', 'fade', 'infinite', 'dots', 'arrows', 'rtl'}
            and isinstance(value, (bool, int, float))}
        current = next((i for i, slide in enumerate(originals) if 'slick-current' in slide.get('class', [])), 0)
        options.update(initialSlide=current, infinite=len(slides) > len(originals),
                       slidesToShow=max(1, sum('slick-active' in slide.get('class', []) for slide in originals)))
        options.setdefault('dots', any('slick-dots' in node.get('class', []) for node in extras))
        for name, option in [('slick-prev', 'prevArrow'), ('slick-next', 'nextArrow')]:
            arrow = next((node for node in extras if name in node.get('class', [])), None)
            if arrow is not None:
                options[option] = str(arrow)  # Includes the candidate's accessible name/markup.
        options.setdefault('arrows', 'prevArrow' in options or 'nextArrow' in options)
        parts = [_content(slide).extract() for slide in originals]
        root.clear()
        for part in parts:
            root.append(part)
        root['class'] = [value for value in root.get('class', []) if value not in {
            'slick-initialized', 'slick-slider', 'slick-dotted', 'slick-vertical'}]
        root['data-warp-frozen-slick'] = str(index)
        root['data-warp-slick-options'] = json.dumps(options, separators=(',', ':'))
        root['data-warp-replay-status'] = 'prepared'
        evidence.append({'component': 'slick', 'version': VERSION, 'runtime_sha256': digest,
                         'widget': str(index), 'slides': len(originals),
                         'duplicate_presentations_removed': len(slides) - len(originals),
                         'options': options,
                         'method': 'retain frozen content; scoped jQuery reconstruction guard; same Slick library',
                         'limitations': 'not a native-DOM mutation sandbox or proof of task equivalence'})
    if evidence and not soup.select('script[data-warp-frozen-carousel-runtime]'):
        script = soup.new_tag('script')
        script['data-warp-frozen-carousel-runtime'] = VERSION
        script.string = runtime
        (soup.head or soup).insert(0, script)
    return evidence


def replay_manifest(html):
    """Record the actual replay code retained across idempotent iterations."""
    soup = BeautifulSoup(html, 'html.parser')
    result = [{'version': node.get('data-warp-frozen-carousel-runtime'),
             'runtime_sha256': hashlib.sha256(node.get_text().encode()).hexdigest(),
             'widgets': len(soup.select('[data-warp-frozen-slick]'))}
            for node in soup.select('script[data-warp-frozen-carousel-runtime]')]
    result.extend({'version': node.get('data-warp-frozen-chat-runtime'),
                   'runtime_sha256': hashlib.sha256(node.get_text().encode()).hexdigest(),
                   'widgets': len(soup.select('.ochat_slideout, #ochat_modal'))}
                  for node in soup.select('script[data-warp-frozen-chat-runtime]'))
    return result


def carousel_warnings(original, evaluated):
    before = BeautifulSoup(original, 'html.parser').select('.slick-initialized')
    after = BeautifulSoup(evaluated, 'html.parser').select('.slick-initialized, [data-warp-frozen-slick]')
    warnings = []
    for index, source in enumerate(before):
        source_count = len(source.select('.slick-slide:not(.slick-cloned)'))
        if not source_count:
            continue
        target = next((node for node in after if source.get('id') and node.get('id') == source['id']), None)
        if target is None and index < len(after):
            target = after[index]
        if target is None:
            warnings.append({'component': 'slick', 'widget': index, 'evidence': 'captured carousel missing after replay'})
            continue
        count = len(target.select('.slick-slide:not(.slick-cloned)'))
        if not target.select('.slick-track') or count > source_count:
            warnings.append({'component': 'slick', 'widget': index, 'source_count': source_count,
                             'rendered_count': count, 'evidence': 'missing track or duplicated original slides after replay'})
    return warnings
