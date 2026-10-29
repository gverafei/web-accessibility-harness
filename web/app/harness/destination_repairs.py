"""Exact source-label witnesses for repairing invented regeneration URLs."""
import json
from collections import defaultdict
from urllib.parse import urljoin
from bs4 import BeautifulSoup

VERSION='source-grounded-destination-repair-v1'


def cases(reference, candidate, url, invalid_targets):
    """No fuzzy URL guessing: one exact label, one distinct source destination."""
    original=BeautifulSoup(reference,'html.parser');soup=BeautifulSoup(candidate,'html.parser')
    normalize=lambda node:' '.join((node.get('aria-label')or node.get_text(' ',strip=True)).split()).casefold()
    labels=defaultdict(set)
    for node in original.select('a[href]'):
        if normalize(node):labels[normalize(node)].add(urljoin(url,node['href']))
    targets={entry['target']for entry in invalid_targets if entry.get('element')=='a'and entry.get('attribute')=='href'}
    result=[]
    for node in soup.select('a[href]'):
        before=node['href'];destinations=labels.get(normalize(node),set())
        if urljoin(url,before)not in targets or len(destinations)!=1:continue
        selector='a[href='+json.dumps(before,ensure_ascii=False)+']'
        matches=soup.select(selector)
        if any(normalize(match)!=normalize(node)for match in matches):continue
        after=next(iter(destinations))
        if before!=after and not any(row['selector']==selector for row in result):
            result.append({'selector':selector,'attribute':'href','before':before,'after':after,
                           'label':node.get_text(' ',strip=True),'match_count':len(matches),
                           'source_witness':'Exact normalized accessible label with one distinct acquired destination'})
    return result


def permits(soup, operation, authorized):
    if operation.get('action')!='set_attribute' or operation.get('name')!='href':return False
    for row in authorized:
        if operation.get('selector')!=row['selector']or operation.get('value')!=row['after']:continue
        try:nodes=soup.select(row['selector'])
        except Exception:return False
        return len(nodes)==row['match_count'] and bool(nodes) and all(n.name=='a'and n.get('href')==row['before']for n in nodes)
    return False
