"""Presentation-only search and pagination; never used by analysis or export."""
import math
from urllib.parse import urlencode

SIZES=(5,10,25,50,100,200)

def paginate(rows,args,search=None):
    query=str(args.get('q','')).strip()[:240]
    if query:
        rows=[r for r in rows if query.casefold() in str(search(r) if search else r).casefold()]
    try: size=int(args.get('per_page',5))
    except (TypeError,ValueError): size=5
    if size not in SIZES:size=5
    pages=max(1,math.ceil(len(rows)/size))
    try: page=max(1,min(pages,int(args.get('page',1))))
    except (TypeError,ValueError):page=1
    base={k:v for k,v in args.items() if k not in ('page','q','per_page')}
    def link(n):return '?'+urlencode(base|{'q':query,'per_page':size,'page':n})
    return rows[(page-1)*size:page*size],dict(q=query,page=page,pages=pages,per_page=size,total=len(rows),sizes=SIZES,
        previous=link(page-1) if page>1 else None,next=link(page+1) if page<pages else None,filters=base)
