"""Read-only catalog with support derived from the measurement implementation."""
import json
from pathlib import Path
from . import CATALOG, RUBRICS, CURATION
from .inventory import TEXTUAL
from .semantic_context import RELATIONAL

ROOT=Path(__file__).parent
AXE=json.loads((ROOT/'axe_rules.json').read_text())
AXE_RULES={row['id']:row for row in AXE['rules']}
ES=json.loads((ROOT/'criteria_es.json').read_text())

def describe(rule, locale='en'):
    row=dict(rule)
    row['criterion']=CURATION.get('operational_criteria',{}).get(rule['id'],{}).get(locale) or (ES[rule['id']] if locale=='es' else rule['description'])
    row['review']=next((item for item in CURATION.get('criterion_review',[]) if item['type']==rule['id']),{})
    typ=rule['id']
    if typ in CURATION['excluded_types']:
        row.update(support='Outside the study scope',detector='Not assessed',evidence=CURATION['excluded_types'][typ])
    elif typ in TEXTUAL|RELATIONAL:
        row.update(support='Contextual judgment',detector='Decisions Luna',evidence='Observed HTML, text and component context' if typ in TEXTUAL else 'Observed configured purpose, relationships and verified state where required')
    elif typ=='image-alt-not-descriptive':
        row.update(support='Verified image judgment',detector='Luna vision',evidence='Verified image bytes and surrounding context')
    elif rule['category']=='Semantic':
        row.update(support='Additional evidence required',detector='Not implemented for this evidence',evidence='Observed destination, interaction state, or media content')
        if typ=='video-captions-inaccurate':
            row.update(support='Applicability only',detector='Video streams + Decisions Luna',evidence='Verified media streams can establish that captions do not apply. Spoken content and captions are not compared yet.')
    else:
        tags=AXE_RULES[typ]['tags']
        wcag=any(tag.startswith('wcag') for tag in tags)
        row.update(support='According to WCAG profile' if wcag else 'Outside the measurement profile',
                   detector='Axe' if wcag else 'Axe best practices',evidence='Rendered document and the selected Axe profile')
        if typ=='bypass':row.update(detector='Axe + snapshot applicability',evidence='Rendered document; simple paragraph-only snapshots without a repeated navigation/control block are not applicable. Ambiguous blocks remain unassessed.')
        if typ=='color-contrast':row.update(detector='Measured contrast + Decisions Luna',evidence='Rendered text, verified background colors, font size and weight')
        if typ=='video-caption':row.update(detector='Video streams + Decisions Luna',evidence='Verified audio tracks and caption tracks; HTML alone is insufficient')
    row['adaptations']=[a for a in CURATION['adaptations'] if typ in a['types']]
    row['rubric']=RUBRICS.get(typ,'')
    return row

def catalog_rows(locale='en',category='',q='',include_excluded=False):
    needle=q.casefold()
    return [describe(row,locale) for row in CATALOG['violations']
            if (include_excluded or row['id'] not in CURATION['excluded_types']) and (not category or category==row['category']) and
            (not needle or needle in ' '.join([row['id'],row['description'],ES[row['id']],*row['wcag']]).casefold())]
