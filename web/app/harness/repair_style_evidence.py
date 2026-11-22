"""Show existing repair declarations beside observed styles, without simulating CSS."""
import re

from bs4 import BeautifulSoup
from grounded_patch_context import top_level_selector

VERSION = 'measured-repair-style-evidence-v6'


def observed_repairs(source, audit):
    """Bind flat, harness-inserted rules to measured current-source targets.

    This is evidence for inspecting the cascade, not a cascade implementation.
    Only rules already present in the editable document are considered; rejected
    branches and proposed-but-unapplied operations cannot enter this projection.
    """
    if source is None:
        return []
    soup = BeautifulSoup(source, 'html.parser')
    rules = []
    for style in soup.select('style[data-warp-repair="true"]'):
        css = style.get_text()
        for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
            selector, declarations = match.groups()
            selector = selector.strip()
            # The patch guard permits flat scoped rules. Fail closed if handed
            # other markup; never mistake a conditional/nested rule for active CSS.
            if '@' in css or '{' in declarations:
                continue
            try:
                targets = {id(node) for node in soup.select(selector)}
            except Exception:
                continue
            if targets:
                rules.append((targets, match.group().strip()))
    evidence = []
    seen = set()
    for failure in audit.get('patch_failures') or []:
        for node in failure.get('nodes') or []:
            selector = top_level_selector(node.get('target'))
            measured = node.get('computed_style')
            if not selector or not isinstance(measured, dict) or not measured:
                continue
            try:
                targets = soup.select(selector)
            except Exception:
                continue
            # A selector shared by multiple nodes cannot identify the observed
            # instance. Keep that audit finding, but don't certify style linkage.
            if len(targets) != 1:
                continue
            matched = list(dict.fromkeys(css for ids, css in rules if id(targets[0]) in ids))
            if not matched or selector in seen:
                continue
            seen.add(selector)
            evidence.append({
                'target': selector,
                'present_repair_rules': matched,
                'observed_computed_style': dict(measured),
                'measured_failure': node.get('failure'),
            })
    return evidence


INSTRUCTION = (
    'applied_style_evidence links repair CSS present in the CURRENT editable page '
    'to that page’s measured computed styles. An applied declaration is not proof '
    'that it wins the cascade. Compare the declared and observed values before '
    'changing another color. If the intended value is not rendered, inspect '
    'specificity, importance, inline styles and runtime overrides; a differently '
    'chosen color with the same losing selector will not solve that cause. A '
    'bounded rule may use !important within the existing CSS permissions when '
    'justified. Do not add it indiscriminately or change layout/content. These '
    'observations do not establish the winning rule or predict repaired contrast.'
)
