"""Plain recorded failure counts shared by reports, lists and CSV exports."""
DIMENSIONS = (('Syntactic', 'Syntactic', 'syntactic'),
              ('Semantic', 'Semantic', 'semantic'),
              ('Layout', 'Layout', 'layout'))


def failure_count(group):
    if not isinstance(group, dict) or not group.get('judged'):
        return None
    value = group.get('failed')
    return value if type(value) is int and value >= 0 else None


def counts(measurement):
    measurement = measurement if isinstance(measurement, dict) else {}
    before = measurement.get('original') or measurement.get('summary') or {}
    after = measurement.get('retained') or {}
    before = before.get('categories', {})
    after = after.get('categories', {})
    return [{'category':category, 'label':label, 'key':key,
             'before':failure_count(before.get(category)),
             'after':failure_count(after.get(category)),
             'partial':bool(before.get(category, {}).get('unassessed') or
                            after.get(category, {}).get('unassessed') or measurement.get('errors'))}
            for category,label,key in DIMENSIONS]


def details(measurement, store=None):
    """Read exact immutable detector evidence, without recomputing verdicts."""
    from . import RULES
    measurement = measurement if isinstance(measurement, dict) else {}
    grouped = {}; missing = []; supplements = {}
    for phase in ('original', 'retained'):
        ident = measurement.get(phase + '_assessment_id')
        if ident and store:
            try: data = store.get(ident)['data']
            except KeyError:
                missing.append(phase); continue
        elif phase == 'original' and 'opportunities' in measurement:
            data = measurement
        else: continue
        for opportunity in data.get('opportunities', []):
            typ = opportunity.get('type'); rule = RULES.get(typ, {})
            method = opportunity.get('method') or 'unrecorded'
            model = (data.get('model') or {}).get('model', '') if method in ('decisions','rendered_decisions','luna_contextual') else ''
            judge = 'Luna high' if model == 'openai/gpt-6-luna' and (data.get('model') or {}).get('reasoning_effort') == 'high' else 'Decisions Luna'
            key = (typ, method, model)
            row = grouped.setdefault(key, {'type':typ, 'category':rule.get('category','Unclassified'),
                'detector':('Measured contrast + '+judge if typ=='color-contrast' else 'Video streams + '+judge) if method=='rendered_decisions' else 'Axe + snapshot applicability' if method=='snapshot_bypass_applicability' else 'Luna vision' if method=='luna_vision' else 'Axe' if method=='axe' else judge if method in ('decisions','luna_contextual') else model or method,
                'before':0, 'after':0, 'unassessed_before':0, 'unassessed_after':0, 'evidence':[], 'pending_evidence':[]})
            column = 'before' if phase=='original' else 'after'
            if method=='rendered_decisions' and typ in ('color-contrast','video-caption'):
                evidence=opportunity.get('supplementary_evidence',{});observed=evidence.get('evidence',{})
                target=' · '.join(map(str, opportunity.get('target') or []))
                supplemental=supplements.setdefault((typ,target),{'type':typ,'target':target,'detector':row['detector']})
                supplemental[column]={'status':opportunity['status'],'ratio':observed.get('measurement',{}).get('ratio'),'threshold':observed.get('measurement',{}).get('threshold'),'audio_tracks':observed.get('media',{}).get('audio_tracks'),'media_sha256':observed.get('media',{}).get('sha256')}

            status = opportunity.get('status')
            if status == 'failed':
                row[column] += 1
                context = opportunity.get('context') or {}; element = context.get('element') or {} if isinstance(context,dict) else {}
                target = ' · '.join(map(str, opportunity.get('target') or [])) or opportunity.get('identity_basis') or opportunity.get('opportunity_id')
                row['evidence'].append({'phase':phase, 'target':target, 'text':str(element.get('attributes', {}).get('alt') or element.get('text') or '')[:400]})
            elif status in ('insufficient_evidence','error'):
                row['unassessed_'+column] += 1
                row['pending_evidence'].append({'phase':phase,'target':' · '.join(map(str,opportunity.get('target') or [])) or opportunity.get('identity_basis') or opportunity.get('opportunity_id')})
    rows = [r for r in grouped.values() if r['before'] or r['after']]
    pending=[r for r in grouped.values() if r['unassessed_before'] or r['unassessed_after']]
    for row in pending:
        row['reason']='Outside automated scope: supplementary evidence is not captured.' if row['detector']=='unobserved_supplement' else 'Axe requires additional verification.' if row['detector']=='Axe' else 'The contextual judge could not establish a verdict from the supplied evidence.'
        reasons={'color-contrast':"Overlapping elements prevent Axe from determining the background color.",
                 'video-caption':"Axe cannot determine whether the video requires captions from HTML alone.",
                 'bypass':"Axe requires verification of bypass navigation.",
                 'link-text-mismatch':"Destination content is required to compare the link label with its destination.",
                 'button-label-mismatch':"Observed control behavior is required to compare the label with its action.",
                 'video-captions-inaccurate':"Audio and caption content are required to judge their correspondence."}
        row['reason']=reasons.get(row['type'],row['reason'])
    return {'rows':sorted(rows,key=lambda r:(r['category'],r['type'],r['detector'])), 'missing':missing,
            'supplements':sorted(supplements.values(),key=lambda x:(x['type'],x['target'])), 'available':bool(grouped), 'pending':sorted(pending,key=lambda r:(r['category'],r['type']))}
