"""Zero-shot, single-pass HTML remediation adapted from snippet studies.

Delnevo (CCNC 2024) asks whether snippets are accessible. Here a direct
remediation instruction requests one whole page; this is not a replication.
"""
import re

from remediation_content_contract import original_page_wrapper
from remediation_output_format import output_format

REFERENCE = 'https://doi.org/10.1109/CCNC51664.2024.10454680'
PROMPT_VERSION = 'full-page-zero-shot-document-v3'
NAME = 'Zero-shot, single-pass HTML remediation'


def baseline_prompt(source):
    return ('Correct accessibility defects in the following HTML code.\n'
            'Return only one complete corrected HTML document, from <!doctype html> through </html>, without an assessment, explanation or suggested snippets. '
            'Preserve all source text, destinations, images, form controls and tasks. Do not return only a suggested snippet.\n'
            'Use concise HTML and CSS to fit the complete document in the response.\n'
            'Correct the supplied content directly. Do not embed or redirect to the original page in an iframe as a substitute for remediation.\n'
            + source)


def baseline_messages(source):
    """Final transport boundary: one instruction plus HTML, no harness context."""
    return [{'role': 'user', 'content': baseline_prompt(source)}]


def baseline_candidate(response, source, base_url=None, *, retain_raw=True):
    """Unwrap one response, never repair it or substitute the source.

    Multiple fenced candidates or document roots are ambiguous. Partial and
    malformed markup is still a browser-evaluable observation.
    """
    response = response or ''
    blocks = re.findall(r'```[^\n]*\n(.*?)(?:```|\Z)', response, re.S)
    html_blocks = [block for block in blocks if output_format(block) != 'no-html-document']
    ambiguous = len(html_blocks) > 1
    # Only an explicit transport wrapper can be removed. Searching for a tag
    # anywhere in prose can turn a refusal's quoted examples into a fake page.
    candidate = html_blocks[0].strip() if len(html_blocks) == 1 else response
    leading = candidate.lstrip('\ufeff \t\r\n')
    markup_boundary = bool(re.match(r'<(?:!doctype\b|!--|\?xml\b|/?[a-z][\w:-]*(?:\s|>|/|$))', leading, re.I))
    ambiguous = ambiguous or len(re.findall(r'<html\b', candidate, re.I)) > 1
    kind = output_format(candidate) if markup_boundary else 'no-html-document'
    evaluable = kind != 'no-html-document' and not ambiguous
    wrapper = evaluable and original_page_wrapper(candidate, source, base_url)
    return candidate, {
        'output': 'ambiguous HTML outputs retained' if ambiguous else
                  'original-page iframe wrapper retained' if wrapper else
                  'HTML output retained' if evaluable else 'response retained without evaluable HTML',
        'reference': REFERENCE, 'prompt_version': PROMPT_VERSION,
        'complete_document': kind == 'html-document', 'format': kind,
        'evaluable': evaluable, 'ambiguous': ambiguous, 'original_page_wrapper': bool(wrapper),
        'extraction_version': 'transport-wrapper-only-v2',
        'reproduction': False,
    }
