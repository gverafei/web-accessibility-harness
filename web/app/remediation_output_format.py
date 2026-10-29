"""Describe returned markup without repairing, substituting or rejecting raw output."""
import re
import json
from pathlib import Path

def output_format(value):
    if re.search(r'<html\b[^>]*>',value,re.I) and re.search(r'</html\s*>',value,re.I):
        return 'html-document'
    if re.search(r'<(?:!doctype\b|/?(?:html|head|body|main|section|article|div|form|nav|p|h[1-6]|input|img|button|a|table|ul|ol|span)\b)[^>]*(?:>|$)', value, re.I):
        return 'html-fragment'
    return 'no-html-document'

def recorded_output_format(path,run_id,dataset_root):
    """Historical read-only projection; exact saved bytes, scoped to this run."""
    if not path:return None
    root=(Path(dataset_root)/'remediations'/str(run_id)).resolve()
    candidate=Path(path).resolve()
    if root not in candidate.parents:return None
    try:
        evidence = candidate.parent / 'baseline-output.json'
        if candidate.name == 'response.txt' and evidence.is_file():
            if json.loads(evidence.read_text()).get('evaluable') is False:
                return 'no-html-document'
        return output_format(candidate.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return None
