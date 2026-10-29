"""Bind advisory findings to the exact editable page without rewriting measurements."""
from hashlib import sha256
from bs4 import BeautifulSoup
from grounded_patch_context import top_level_selector
from remediation_patch_context import contextual_targets

VERSION = 'source-bound-context-repair-v4'


def bindings(evidence, source):
    if source is None:
        return {'status': 'unavailable', 'scope': 'No editable source supplied; no target identity certified.'}
    soup = BeautifulSoup(source, 'html.parser')
    rows = []
    for index, finding in enumerate(evidence.get('failed_opportunities', [])):
        element = (finding.get('context') or {}).get('element')
        selectors = []
        status = 'unresolved'
        if element:
            selectors, missing = contextual_targets(soup, {'failed_opportunities': [finding]})
            status = 'verified_element' if selectors else missing[0]['status']
        else:
            selector = top_level_selector(finding.get('target'))
            if selector:
                try:
                    matches = soup.select(selector)
                    if matches:
                        selectors = [selector]
                        status = 'selector_matches_source'
                    else:
                        status = 'no_match'
                except Exception:
                    status = 'invalid_selector'
            else:
                status = 'nested_or_unsupported_target'
        rows.append({'finding_index': index, 'status': status, 'editable_selectors': selectors})
    return {'status': 'completed', 'document_sha256': sha256(source.encode()).hexdigest(),
            'findings': rows,
            'scope': 'Static editable source only. A source match is not a new accessibility judgment or permission. Unresolved targets remain measured defects; rendered-only selectors cannot be copied into edits.'}


CURRENT_VERSION = 'role-and-source-bound-repair-v5'
SUPPORTED_VERSIONS = (VERSION, CURRENT_VERSION)


def role_instruction(role):
    contracts = {
        'component-planner': (
            'Your task is COMPONENT PLANNING, not patch generation. Return the requested JSON '
            'components array and rationale. Each component entry identifies id, area, intervention, '
            'root_cause, depends_on and reason. Propose evidence-grounded component work; this role '
            'does not execute operations and does not need to supply CSS values. Do not return '
            'operations, root_causes or a diagnosis in place of components.'),
        'repair-diagnostician': (
            'Your task is REPAIR DIAGNOSIS. Return only the requested JSON summary and findings '
            'array of grounded recommendations. Do not return components or patch operations.'),
        'repair-generator': (
            'Your task is REPAIR GENERATION. Follow the intervention and output contract in the '
            'base prompt: patches use operations and root_causes; regeneration uses its requested '
            'HTML contract. Do not return a component inventory or diagnosis instead of the repair.'),
    }
    return contracts.get(role, contracts['repair-generator'])


def component_output_format():
    """Typed output for P2's component planner; semantic validation still follows."""
    return {'type': 'json_schema', 'json_schema': {
        'name': 'coordinated_component_plan', 'strict': True,
        'schema': {'type': 'object', 'additionalProperties': False,
            'required': ['components', 'rationale'], 'properties': {
                'rationale': {'type': 'string'},
                'components': {'type': 'array', 'items': {
                    'type': 'object', 'additionalProperties': False,
                    'required': ['id', 'area', 'intervention', 'root_cause', 'depends_on', 'reason'],
                    'properties': {'id': {'type': 'string'},
                        'area': {'type': 'string', 'enum': ['header', 'main', 'footer']},
                        'intervention': {'type': 'string', 'enum': ['preserve', 'repair']},
                        'root_cause': {'type': 'string'},
                        'depends_on': {'type': 'array', 'items': {'type': 'string'}},
                        'reason': {'type': 'string'}}}}}}}}
