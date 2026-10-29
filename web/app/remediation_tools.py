"""Shared descriptions of the executable remediation tool contracts."""
from remediation_tool_registry import ToolContract


TOOL_CONTRACTS = {
    'inspect_dom': ToolContract(
        'inspect_dom', '1.0', 'Build a bounded structural/content inventory', ('html', 'base_url'), 'object', True),
    'read_axe_evidence': ToolContract(
        'read_axe_evidence', '1.0', 'Read bounded measured Axe failures', ('path',), 'array', True),
    'read_lighthouse_evidence': ToolContract(
        'read_lighthouse_evidence', '1.0', 'Read bounded Lighthouse accessibility failures', ('path',), 'array', True),
    'retrieve_accessibility_evidence': ToolContract(
        'retrieve_accessibility_evidence', '1.0', 'Retrieve complete matching evidence pairs', ('query', 'limit', 'previously_supplied'), 'array', True),
    'apply_constrained_patch': ToolContract(
        'apply_constrained_patch', '1.0', 'Apply validated selector-scoped operations', ('document', 'plan'), 'tuple', True, True),
    'prepare_frozen_widgets': ToolContract(
        'prepare_frozen_widgets', '2.0', 'Normalize recognized captured widgets for bounded replay', ('html',), 'tuple', True, True),
    'evaluate_candidate': ToolContract(
        'evaluate_candidate', '1.0', 'Run Axe and Lighthouse through the evaluator service', ('request_payload',), 'object', True),
    'measure_content_retention': ToolContract(
        'measure_content_retention', '1.0', 'Measure text, URL and media retention', ('original', 'candidate', 'base_url'), 'object', True),
    'compare_visual_evidence': ToolContract(
        'compare_visual_evidence', '1.0', 'Compare available captures for ranking only', ('original_path', 'candidate_path'), 'number_or_null', True),
    'select_best_candidate': ToolContract(
        'select_best_candidate', '2.0', 'Produce deterministic candidate rank', ('quality', 'retention', 'visual', 'step', 'axe', 'lighthouse'), 'tuple', True),
    'plan_components': ToolContract(
        'plan_components', '1.0', 'Detect source-owned component candidates', ('html',), 'array', True),
    'capture_screenshot': ToolContract(
        'capture_screenshot', '1.0', 'Read an existing screenshot as model visual evidence', ('path',), 'array', True),
    'extract_content_inventory': ToolContract(
        'extract_content_inventory', '1.0', 'Extract ordered content, media and controls', ('html', 'base_url'), 'object', True),
    'extract_markdown': ToolContract(
        'extract_markdown', '1.0', 'Produce a source-grounded Markdown representation', ('html', 'base_url', 'provider'), 'object', True),
}
