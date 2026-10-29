"""Paginated read-only taxonomy; no paid calls."""
from flask import Blueprint,render_template,request,url_for
from flask_babel import get_locale
from accessibility_taxonomy.explorer import catalog_rows,CATALOG,AXE,CURATION
from rag_examples import PAGE_SIZES

taxonomy_bp=Blueprint('taxonomy',__name__)
@taxonomy_bp.get('/taxonomy')
def index():
    category=request.args.get('category','')
    if category not in ('Syntactic','Semantic','Layout'):category=''
    q=request.args.get('q','')[:200]
    locale=str(get_locale())
    active_rows=catalog_rows(locale)
    rows=catalog_rows(locale,category,q)
    try:size=int(request.args.get('size',20))
    except ValueError:size=20
    if size not in PAGE_SIZES:size=20
    pages=max(1,(len(rows)+size-1)//size)
    try:page=max(1,min(int(request.args.get('page',1)),pages))
    except ValueError:page=1
    def browse_url(number):
        return url_for('taxonomy.index',category=category,q=q,size=size,page=number)
    return render_template('taxonomy.html',rows=rows[(page-1)*size:page*size],category=category,q=q,matched=len(rows),
       sizes=PAGE_SIZES,size=size,page=page,pages=pages,browse_url=browse_url,
       total=len(active_rows),category_counts={name:sum(row['category']==name for row in active_rows) for name in ('Syntactic','Semantic','Layout')},
       contextual_count=sum(row['support']=='Contextual judgment' for row in active_rows),
       catalog=CATALOG,curation=CURATION,axe_version=AXE['version'])
