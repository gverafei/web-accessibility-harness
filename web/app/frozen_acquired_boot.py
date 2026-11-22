"""Preserve an acquired DOM state without rerunning its application initializers.

This supports frozen state measurements, not restoration of event handlers or
proof that application/server tasks work. Newly generated scripts remain active.
"""
VERSION = 'frozen-acquired-boot-v1'
MARKER = 'data-warp-frozen-acquired-boot'
INERT = 'application/x-a11yharness-acquired-script'
EXECUTABLE = {'', 'module', 'text/javascript', 'application/javascript',
              'text/ecmascript', 'application/ecmascript'}


def suspend_acquired_boot(soup):
    scripts = []
    for node in soup.find_all('script'):
        kind = node.get('type', '').strip().lower()
        if kind not in EXECUTABLE or any(str(key).startswith('data-warp-') for key in node.attrs):
            continue
        scripts.append({'src': node.get('src'), 'original_type': node.get('type'),
                        'reason': 'Acquired document initialization must not run again'})
        node[MARKER] = VERSION
        node['data-warp-original-script-type'] = node.get('type', '')
        node['type'] = INERT
    if not scripts:
        return []
    return [{'component': 'acquired-document-boot', 'version': VERSION,
             'scripts': scripts, 'stored_source_modified': False,
             'scope': 'Frozen observed DOM state only; event handlers and tasks are unverified'}]
