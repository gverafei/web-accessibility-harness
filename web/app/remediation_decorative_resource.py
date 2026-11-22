"""A bounded repair for an empty, explicitly tiny, non-informative IMG.

This is an operation permission, never an automatic page postprocessor. Links,
controls and informative images remain in the document. URLs are not guessed.
"""
import re

VERSION='empty-decorative-image-removal-v1'


def removable(node):
    if node.name!='img' or node.get('src') not in (None,''):return False
    if node.get('alt') not in (None,''):return False
    if any(node.has_attr(k) for k in ('title','aria-label','aria-labelledby','role','tabindex','onclick')):return False
    style=node.get('style','')
    def size(key):
        rules=re.findall(r'(?:^|;)\s*'+key+r'\s*:\s*([^;]+)',style,re.I)
        if rules:return bool(re.fullmatch(r'1px\s*(?:!important)?\s*',rules[-1],re.I))
        return str(node.get(key,'')).strip()=='1'
    if not(size('width') and size('height')):return False
    control=node.find_parent(['a','button']) or node.find_parent(attrs={'role':'button'})
    if control is not None:
        # Preserve a named carrier; never delete its only accessible content.
        if not(control.get('aria-label','').strip() or control.get_text(' ',strip=True)):return False
    if node.get('id'):
        root=node
        while root.parent is not None:root=root.parent
        ident=node['id']
        if any(ident in str(n.get(a,'')).split() for n in root.find_all(True) for a in ('aria-labelledby','aria-describedby','aria-controls','for')):return False
        if any(n.get('href')=='#'+ident for n in root.find_all('a')):return False
    return True
