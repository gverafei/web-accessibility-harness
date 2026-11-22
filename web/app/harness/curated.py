"""Immutable curated metadata, ranked eligibility and domain-disjoint partitions."""
import csv
import hashlib
import io
import re
from urllib.parse import urlsplit
from .contracts import ContractError,digest,number,public_url,text

VERSION='curated-cohort-v1'

def import_source(store,raw,metadata):
    if len(raw)>12000000:raise ContractError('Curated source exceeds twelve megabytes')
    name=text(metadata.get('name'),'dataset name',240)
    version=text(metadata.get('version'),'dataset version',240)
    list_hash=text(metadata.get('list_sha256'),'ranking list hash',64)
    if not re.fullmatch('[0-9a-fA-F]{64}',list_hash):raise ContractError('Ranking list hash must be a SHA-256 digest')
    cutoff=number(metadata.get('rank_cutoff',10000),'rank cutoff',1,1000000,True)
    seed=text(str(metadata.get('seed','20261008')),'partition seed',240)
    dev=number(metadata.get('development_fraction',.2),'development fraction',.01,.8)
    val=number(metadata.get('validation_fraction',.2),'validation fraction',.01,.8)
    if dev+val>=1:raise ContractError('Reserve a separate test partition')
    rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
    if not rows or not {'id','url','tranco_rank','site_category'}<=set(rows[0]):raise ContractError('CSV requires id, url, tranco_rank and site_category')
    ids=set();eligible=[];excluded=[]
    categories={str(c).strip().casefold() for c in metadata.get('excluded_categories',[])}
    if 'gambling' in categories:categories.add('gambling/casinos')
    for row in rows:
        ident=text(row['id'],'source page identifier')
        if ident in ids:raise ContractError('Duplicate curated source page identifier')
        ids.add(ident);rank=number(row['tranco_rank'],'original Tranco rank',1,1000000,True)
        url=public_url(row['url']);domain=urlsplit(url).hostname.lower().removeprefix('www.')
        captured=public_url(row.get('captured_url') or url)
        item={'source_id':ident,'rank':rank,'url':url,'domain':domain,'captured_url':captured,
              'category':row['site_category'],'category_source':row.get('site_category_source',''),
              'title':row.get('page_title',''),'acquisition_date':row.get('evaluated_at') or row.get('created_at'),
              'source_result_id':row.get('source_result_id')}
        reason='outside_rank_cutoff' if rank>cutoff else 'excluded_category' if row['site_category'].casefold() in categories else None
        if reason:excluded.append(item|{'reason':reason})
        else:eligible.append(item)
    eligible.sort(key=lambda r:(r['rank'],r['source_id']))
    # Requested and redirected domains share a component, preventing alias leakage.
    parent={}
    def root(x):
        parent.setdefault(x,x)
        if parent[x]!=x:parent[x]=root(parent[x])
        return parent[x]
    for item in eligible:
        a=root(item['domain']);b=root(urlsplit(item['captured_url']).hostname.lower().removeprefix('www.'))
        parent[max(a,b)]=min(a,b)
    for item in eligible:
        group=root(item['domain']);u=int(digest({'seed':seed,'domain':group})[:16],16)/16**16
        item.update(partition='development' if u<dev else 'validation' if u<dev+val else 'test',partition_domain=group)
    artifact=store.blob(raw,'curated_metadata',media_type='text/csv')
    return store.append('curated_source',{'version':VERSION,'name':name,'dataset_version':version,'metadata_id':artifact['id'],
        'csv_sha256':hashlib.sha256(raw).hexdigest(),'list_id':text(metadata.get('list_id'),'ranking list ID'),
        'list_sha256':list_hash.lower(),'rank_cutoff':cutoff,
        'provenance':text(metadata.get('provenance'),'dataset provenance',3000),'excluded_categories':sorted(categories),
        'partition_seed':seed,'development_fraction':dev,'validation_fraction':val,'candidates':eligible,'exclusions':excluded,
        'source_count':len(rows),'within_cutoff':sum(r['rank']<=cutoff for r in eligible+excluded)})

def select_source(store,source,partition,seed):
    record=store.get(source['curated_id'])
    if store.checkpoint('source-view:'+record['id'])[0].get('removed'):raise ContractError('Curated source has been superseded')
    if record['kind']!='curated_source':raise ContractError('Select a curated dataset snapshot')
    frame=[r for r in record['data']['candidates'] if r['partition']==partition]
    count=source['count']
    if count>len(frame):raise ContractError('Requested count exceeds the eligible partition')
    if source.get('selection','seeded')=='seeded':
        frame=sorted(frame,key=lambda r:digest({'seed':seed,'source':record['hash'],'id':r['source_id']}))[:count]
        frame.sort(key=lambda r:r['rank'])
    else:frame=frame[:count]
    return [r|{'order':i,'role':'selected','curated_id':record['id'],'source_hash':record['hash']} for i,r in enumerate(frame)]
