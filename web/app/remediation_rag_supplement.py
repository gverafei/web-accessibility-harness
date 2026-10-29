"""Original illustrative pairs grounded in primary guidance, NOT official ACT cases.

The outcomes refer only to the named rule. They do not certify a page or replace
runtime checks. Upserts are idempotent and never delete the official ACT corpus.
"""
import hashlib
import json
import uuid

import requests

SOURCE = 'Platform-authored examples grounded in Deque/W3C guidance (not official ACT testcases)'
VERSION = 'axe-guidance-pairs-v1'
# rule: (concept, source page, passed body, failed body, applicability guidance)
PAIRS = {
    'page-has-heading-one': ('page has level one heading',
        'https://dequeuniversity.com/rules/axe/4.10/page-has-heading-one',
        '<main><h1>Service information</h1><p>Appointments and support</p></main>',
        '<main><h2>Service information</h2><p>Appointments and support</p></main>',
        'Use the existing page-title content as its level-one heading when justified by the document outline. Preserve text and subordinate heading relationships; do not invent a title or promote every heading.'),
    'landmark-banner-is-top-level': ('banner landmark is outside other landmarks',
        'https://dequeuniversity.com/rules/axe/4.10/landmark-banner-is-top-level',
        '<div role="banner">Service portal</div><main><p>Service information</p></main>',
        '<main><div role="banner">Service portal</div><p>Service information</p></main>',
        'Keep the page banner outside other landmarks. A section-local header is not necessarily a page banner; preserve native semantics and reading order.'),
    'landmark-main-is-top-level': ('main landmark is outside other landmarks',
        'https://dequeuniversity.com/rules/axe/4.10/landmark-main-is-top-level',
        '<nav aria-label="Services"><a href="/services">Services</a></nav><main><p>Service information</p></main>',
        '<nav aria-label="Services"><a href="/services">Services</a><main><p>Service information</p></main></nav>',
        'Primary content belongs in main outside navigation and other landmarks. Do not wrap the entire body in main or create duplicate/nested main landmarks.'),
    'link-in-text-block': ('inline link is distinguishable without color alone',
        'https://dequeuniversity.com/rules/axe/4.10/link-in-text-block',
        '<main style="color:#111;background:#fff"><p>Please read the <a href="https://example.org/policy" style="color:#0044aa;text-decoration:underline">policy</a> before applying.</p></main>',
        '<main style="color:#111;background:#fff"><p>Please read the <a href="https://example.org/policy" style="color:#0044aa;text-decoration:none">policy</a> before applying.</p></main>',
        'For a link within prose, an underline supplies a non-color cue without changing words, destinations or text color. Scope the CSS to actual inline links and preserve visible keyboard focus; do not impose prose-link styling on unrelated controls.'),
    'empty-table-header': ('table header has visible descriptive text',
        'https://dequeuniversity.com/rules/axe/4.10/empty-table-header',
        '<main><table><tr><td></td><th scope="col">Duration</th></tr><tr><th scope="row">Session</th><td>30 minutes</td></tr></table></main>',
        '<main><table><tr><th></th><th scope="col">Duration</th></tr><tr><th scope="row">Session</th><td>30 minutes</td></tr></table></main>',
        'This pair represents an empty corner cell that is not a header: use td rather than inventing a heading. For a real data header, use descriptive visible text derived from the source; aria-label alone does not fix this rule.'),
    'landmark-contentinfo-is-top-level': ('contentinfo landmark is outside other landmarks',
        'https://dequeuniversity.com/rules/axe/4.10/landmark-contentinfo-is-top-level',
        '<main><p>Service information</p></main><div role="contentinfo">Policy</div>',
        '<main><p>Service information</p><div role="contentinfo">Policy</div></main>',
        'Preserve page-footer content and ordering, with the page contentinfo landmark outside main/nav/other landmarks. A section-local footer is not automatically the page footer; do not assign contentinfo to every footer.'),
    'region': ('page content is contained by landmarks',
        'https://dequeuniversity.com/rules/axe/4.10/region',
        '<main><p>Service information</p></main>', '<div><p>Service information</p></div>',
        'Wrap the actual content in the appropriate native landmark. Preserve existing landmarks and reading order; do not replace skip links.'),
    'landmark-one-main': ('document has one main landmark',
        'https://dequeuniversity.com/rules/axe/4.10/landmark-one-main',
        '<main><h1>Services</h1><p>Service information</p></main>',
        '<section><h1>Services</h1><p>Service information</p></section>',
        'Use one main landmark for primary content in this document; do not add nested or duplicate main landmarks.'),
    'listitem': ('list item has list parent',
        'https://dequeuniversity.com/rules/axe/4.10/listitem',
        '<main><ul><li>Appointments</li><li>Support</li></ul></main>',
        '<main><li>Appointments</li><li>Support</li></main>',
        'Preserve all list items and order. Use ul or ol as the direct list parent, according to the content.'),
    'aria-allowed-role': ('ARIA role is allowed for the HTML element',
        'https://dequeuniversity.com/rules/axe/4.10/aria-allowed-role',
        '<main><button type="button">Continue</button></main>',
        '<main><button type="button" role="heading" aria-level="2">Continue</button></main>',
        'Keep a real control a native control. Remove a conflicting role only after verifying its intended function; valid role names can still be disallowed on an element.'),
    'target-size': ('pointer target has sufficient size or spacing',
        'https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html',
        '<main><div style="display:flex;gap:8px"><button style="width:32px;height:32px;padding:0" aria-label="Previous">‹</button><button style="width:32px;height:32px;padding:0" aria-label="Next">›</button></div></main>',
        '<main><div style="display:flex;gap:0"><button style="width:16px;height:16px;padding:0" aria-label="Previous">‹</button><button style="width:16px;height:16px;padding:0" aria-label="Next">›</button></div></main>',
        'This illustrates adjacent undersized targets without spacing. WCAG 2.5.8 allows size OR adequate spacing and has inline, equivalent, user-agent and essential exceptions. Inspect rendered geometry; do not enlarge every inline link blindly.'),
}


def points():
    from remediation_rag import embed
    result = []
    for rule, (concept, page, passed, failed, guidance) in PAIRS.items():
        for expected, body in [('passed', passed), ('failed', failed)]:
            code = '<!doctype html><html lang="en"><head><title>Rule example</title></head><body>' + body + '</body></html>'
            payload = dict(source=SOURCE, source_kind='curated_guidance', version=VERSION,
                rule_id='platform-axe-' + rule, axe_rule=rule, rule_name=concept,
                rule_page=page, expected=expected, code=code, guidance=guidance,
                requirements=[], validation_scope='Named rule only; expected outcome is illustrative, not WCAG certification',
                code_sha256=hashlib.sha256(code.encode()).hexdigest())
            result.append(dict(id=str(uuid.uuid5(uuid.NAMESPACE_URL, VERSION + '/' + rule + '/' + expected)),
                vector=embed(concept + ' ' + guidance + ' ' + code), payload=payload))
    return result


def sync():
    from remediation_rag import QDRANT_URL, COLLECTION
    batch = points()
    requests.put(f'{QDRANT_URL}/collections/{COLLECTION}/points?wait=true',
        json={'points': batch}, timeout=30).raise_for_status()
    return {'supplement': VERSION, 'upserted': len(batch), 'rules': list(PAIRS)}


if __name__ == '__main__':
    print(json.dumps(sync()))
