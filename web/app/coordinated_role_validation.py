"""Versioned patch validation and atomic native list-role checks."""
from bs4 import BeautifulSoup

LEGACY_VERSION = 'coordinated-list-role-validation-v1'
VERSION = 'complete-subtree-patch-validation-v2'
SUPPORTED_VERSIONS = (LEGACY_VERSION, VERSION)
LIST_ROLE_REJECTION = (
    'removing an explicit list role does not repair invalid native list children; '
    'coordinate the child semantics within the permitted scope'
)


def repairs_native_list_children(document, plan, operation_index):
    """Preview only the declared cause and its prerequisites, never other causes.

    The ordinary operation guards still run and can reject the whole cause.
    This preview only resolves the list-child dependency that cannot be checked
    against the pre-repair tree. It grants no new operation or selector authority.
    """
    operations = plan.get('operations', [])
    groups = plan.get('root_causes', [])
    by_id = {group['id']: group for group in groups}
    owners = [group for group in groups
              if operation_index in group.get('operation_indexes', [])]
    if len(owners) != 1:
        return False
    included = set()
    pending = [owners[0]['id']]
    while pending:
        identity = pending.pop()
        if identity in included:
            continue
        if identity not in by_id:
            return False
        included.add(identity)
        pending.extend(by_id[identity].get('depends_on', []))
    indexes = sorted({index for identity in included
                      for index in by_id[identity]['operation_indexes']})
    soup = BeautifulSoup(document, 'html.parser')
    operation = operations[operation_index]
    try:
        targets = soup.select(operation['selector'])
    except (KeyError, ValueError, TypeError, SyntaxError):
        return False
    if not targets or any(node.name not in {'ul', 'ol'} for node in targets):
        return False
    for index in indexes:
        update = operations[index]
        if update.get('action') not in {'set_attribute', 'remove_attribute'}:
            return False
        name = update.get('name')
        if not isinstance(name, str) or not name:
            return False
        try:
            matches = soup.select(update['selector'])
        except (KeyError, ValueError, TypeError, SyntaxError):
            return False
        if not matches:
            return False
        for node in matches:
            if update['action'] == 'remove_attribute':
                node.attrs.pop(name, None)
            else:
                node[name] = str(update.get('value') or '')
    return all(
        child.name == 'li' and child.get('role') in (None, 'listitem', 'none', 'presentation')
        for target in targets for child in target.find_all(recursive=False)
        if child.name not in {'script', 'template'}
    )
