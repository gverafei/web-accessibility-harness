"""Coverage-first localization of measured targets in the current source.

Compact source excerpts are evidence, not additional edit permissions. Legacy
manifests retain their existing localization and replacement contracts.
"""
import json
from bs4 import BeautifulSoup
from soupsieve import escape

VERSION = 'grounded-target-coverage-v1'
COMPONENT_VERSION = 'grounded-component-coverage-v2'
SUPPORTED_VERSIONS = (VERSION, COMPONENT_VERSION)


def top_level_selector(target):
    if isinstance(target, str) and target:
        return target
    if isinstance(target, list) and len(target) == 1 and isinstance(target[0], str):
        return target[0] or None
    return None


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def attributes(node, allowance=180):
    values, abbreviated = {}, []
    for key, value in node.attrs.items():
        size = len(encode(value))
        if size > allowance:
            values[key] = str(value)[:allowance]
            abbreviated.append(key)
        else:
            values[key] = value
    return {'attributes': values, **({'attributes_abbreviated': abbreviated} if abbreviated else {})}


def component_selector(soup, node):
    """Use a short selector only when it identifies this exact source node."""
    from remediation_patch_context import exact_selector
    candidates = [node.name]
    if node.get('id'):
        candidates.append('#' + escape(node['id']))
    if node.get('class'):
        candidates.append(node.name + ''.join('.' + escape(c) for c in node['class']))
    for selector in sorted(candidates, key=len):
        matches = soup.select(selector)
        if len(matches) == 1 and matches[0] is node:
            return selector
    return exact_selector(soup, node)


def repair_context(source, axe_evidence, lighthouse_evidence, limit=50000, *, contextual_evidence=None, version=VERSION):
    from remediation_patch_context import contextual_targets
    if version not in SUPPORTED_VERSIONS:
        raise ValueError('Unknown target coverage contract')
    component_coverage = version == COMPONENT_VERSION
    soup = BeautifulSoup(source, 'html.parser')
    selectors, unresolved = {}, []

    def add(target, instrument):
        selector = top_level_selector(target)
        if selector:
            selectors.setdefault(selector, []).append(instrument)
        elif target:
            unresolved.append({'target': target, 'instrument': instrument,
                               'status': 'nested_or_unsupported_context'})

    for violation in axe_evidence or []:
        for node in violation.get('nodes') or []:
            add(node.get('target'), 'Axe')
    for audit in lighthouse_evidence or []:
        for item in audit.get('items') or []:
            add(item.get('selector'), 'Lighthouse')
    findings = (contextual_evidence or {}).get('failed_opportunities', [])
    for index, finding in enumerate(findings):
        reference = 'contextual:' + str(index)
        # A supplied element identity must still match: a valid CSS path alone
        # cannot override stale or ambiguous semantic evidence.
        if (finding.get('context') or {}).get('element'):
            targets, missing = contextual_targets(soup, {'failed_opportunities': [finding]})
            for target in targets:
                add(target, reference)
            unresolved.extend(dict(item, finding_index=index) for item in missing)
        elif finding.get('target'):
            add(finding['target'], reference)
        else:
            unresolved.append({'finding_index': index, 'status': 'element_identity_unavailable'})

    # Audit and taxonomy can spell the same DOM target differently. Merge only
    # exact match sets, retaining every finding reference and the shortest
    # observed selector. Different sets or unmatched selectors stay separate.
    grouped = {}
    for selector, references in selectors.items():
        try:
            matches = soup.select(selector)
            status = 'matched' if matches else 'no_match'
        except Exception:
            matches, status = [], 'invalid_selector'
        identity = tuple(id(node) for node in matches) if matches else ('unmatched', selector)
        if identity in grouped:
            entry = grouped[identity]
            entry['references'].extend(references)
            if len(selector) < len(entry['selector']):
                entry['selector'] = selector
        else:
            grouped[identity] = {'selector': selector, 'references': list(references),
                                 'matches': matches, 'status': status}
    metadata, observed, components = [], [], []
    component_ids = {}
    for entry in grouped.values():
        selector, references, matches, status = (entry[key] for key in ('selector', 'references', 'matches', 'status'))
        metadata.append({'selector': selector, 'status': status, 'match_count': len(matches),
                         'finding_references': list(dict.fromkeys(references)),
                         **({'instances_omitted': len(matches)-2} if len(matches)>2 else {}), 'elements': []})
        for position, node in enumerate(matches[:2], 1):
            identities = [int(ref.split(':')[1]) for ref in references
                          if ref.startswith('contextual:') and
                          (findings[int(ref.split(':')[1])].get('context') or {}).get('element')]
            component_refs = []
            parents = list(node.parents)[:6] if component_coverage else ([] if identities else list(node.parents)[:3])
            for parent in parents:
                if parent.name == '[document]':
                    break
                # Repeated cards can have identical classes but are different
                # ancestors. Share evidence only for the same actual DOM node.
                if id(parent) not in component_ids:
                    component_ids[id(parent)] = len(components)
                    components.append({'element': parent.name, 'id': parent.get('id'),
                                       'classes': parent.get('class', [])})
                    if component_coverage:
                        components[-1]['selector'] = component_selector(soup, parent)
                        # ID/classes are already present. Do not resend full
                        # utility-class lists inside a second attributes object.
                        if parent.get('style'):
                            style = str(parent['style'])
                            components[-1]['style'] = style[:180]
                            components[-1]['style_truncated'] = len(style) > 180
                component_refs.append(component_ids[id(parent)])
            element = {'match_index': position, 'tag': node.name, 'ancestor_refs': component_refs}
            if identities:
                # This exact source identity is already supplied in full in the
                # contextual message; reference it instead of duplicating it.
                element['contextual_element_reference'] = identities[0]
            else:
                text = node.get_text(' ', strip=True)
                element.update(**attributes(node), text=text[:120])
                if len(text)>120:
                    element['text_truncated'] = True
            metadata[-1]['elements'].append(element)
            observed.append({'selector': selector, 'match_index': position, 'match_count': len(matches),
                             'html': str(node), 'html_length': len(str(node)), 'html_truncated': False})
    payload = {'version': version, 'scope': 'Current static source; no task or visual verification.',
               'document_size': len(source), 'selector_evidence': metadata,
               'measured_selector_count': len(selectors), 'equivalent_selectors_merged': len(selectors)-len(grouped),
               'affected_nodes': [], 'ancestor_evidence': components, 'unresolved_targets': unresolved,
               'selectors_omitted': 0, 'selector_evidence_omitted': 0, 'context_nodes_omitted': 0,
               'unresolved_targets_omitted': 0,
               'ancestor_scope': 'Up to three current ancestors for targets without full contextual element evidence. Distinct references mean distinct DOM nodes even if classes coincide.',
               'contextual_element_references': 'Zero-based failed_opportunities index in the full contextual evidence supplied in this request. context.element was verified against this exact source. ancestor_refs index ancestor_evidence.',
               'coverage_policy': 'Absent per-element truncation/omission flags mean false/zero. Cover measured selectors before expanding excerpts. Truncated or omitted evidence never authorizes replacement. Same-type findings need source-verified shared causes.'}
    if component_coverage:
        payload['ancestor_scope'] = (
            'Up to six current ancestors for every observed target, including contextual identities. '
            'References identify actual shared DOM nodes, not merely similar classes. Selectors are '
            'verified against this current source; attributes may be explicitly abbreviated. '
            'For coordinated repair inspect whether a shared ancestor explains several measured '
            'failures before proposing separate descendant edits. Shared ancestry alone does not '
            'prove a cause. Existing edit permissions and measurement requirements still apply; '
            'ancestor metadata does not authorize subtree replacement.')
    # Keep a compact source-verified description for every target first. Full
    # excerpts can then authorize existing bounded replacements; partial indexes
    # do not. Short complete nodes are affordable without sacrificing coverage.
    for node in sorted(observed, key=lambda item: item['html_length']):
        if node['html_length'] <= 2500:
            payload['affected_nodes'].append(node)
            if len(encode(payload)) <= limit:
                continue
            payload['affected_nodes'].pop()
        payload['context_nodes_omitted'] += 1
    while len(encode(payload)) > limit and payload['unresolved_targets']:
        payload['unresolved_targets'].pop()
        payload['unresolved_targets_omitted'] += 1
    while len(encode(payload)) > limit and payload['selector_evidence']:
        payload['selector_evidence'].pop()
        payload['selector_evidence_omitted'] += 1
        payload['selectors_omitted'] += 1
    if len(encode(payload)) > limit:
        return '{}'
    return encode(payload)
