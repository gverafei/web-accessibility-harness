"""One selection policy for refinement rollback and final publication.

This is a lexicographic engineering objective, not a global improvement score
or additional acceptance threshold. Born designs are not rewarded for copying
the original screenshot.
"""
import math
import json


POLICY='automated targets, protected content, Axe/Lighthouse, then visual tie-break for repair steps 1-3'
OUTCOME_POLICY='any observed improvement from original, candidate usability and visual admission; rank eligible candidates by targets/Axe/Lighthouse, then fidelity as tie-break'
IMPROVEMENT_VERSION='observed-any-metric-improvement-v1'


def improvement_evidence(original_axe, original_lighthouse, axe, lighthouse, taxonomy=None):
    """Observed improvement in any metric; targets and fidelity are not vetoes."""
    gains=[]
    for label,before,after,direction in [('Axe',original_axe,axe,-1),('Lighthouse',original_lighthouse,lighthouse,1)]:
        if type(before)in(int,float) and type(after)in(int,float) and math.isfinite(before)and math.isfinite(after)and direction*(after-before)>0:
            gains.append({'metric':label,'before':before,'after':after})
    if isinstance(taxonomy,dict)and taxonomy.get('status')=='completed':
        before=taxonomy.get('original',{}).get('categories',{});after=taxonomy.get('retained',{}).get('categories',{})
        for category in ['Syntactic','Semantic','Layout']:
            a=before.get(category,{});b=after.get(category,{})
            if a.get('judged',0)>0 and b.get('judged',0)>0 and type(a.get('failed'))is int and type(b.get('failed'))is int and b['failed']<a['failed'] and b.get('unassessed',0)<=a.get('unassessed',0):
                gains.append({'metric':category,'before':a['failed'],'after':b['failed'],
                              'scope':'Observed failure counts with no increased unassessed count; changed/removed opportunities reported separately, not certified repairs.'})
    return {'version':IMPROVEMENT_VERSION,'improved':bool(gains),'gains':gains}


def admitted_improvement(assessment_status, rank, incumbent_rank, *, zero_shot=False, improvement=None, incumbent_original=False):
    """Zero-shot records its one output; harness delivery requires admission."""
    if zero_shot:
        return True
    if improvement is not None:
        return assessment_status=='passed' and improvement.get('improved',False) and (incumbent_original or rank<incumbent_rank)
    return assessment_status == 'passed' and rank < incumbent_rank


def candidate_rank(distance,retention,visual,step,axe=None,lighthouse=None,*,fidelity_priority=True):
    def bounded(value):
        try: number=float(value)
        except (TypeError,ValueError): return 0.0
        return min(100.0,max(0.0,number)) if math.isfinite(number) else 0.0
    retention=retention or {}
    values=[bounded(retention.get(key,100.0)) for key in ('text_percent','links_percent','images_percent','dynamic_images_percent')]
    metrics=(float(axe) if axe is not None else 0.0,-float(lighthouse) if lighthouse is not None else 0.0)
    fidelity=(-min(values),-values[0])
    return (distance,*(fidelity+metrics if fidelity_priority else metrics+fidelity),-bounded(visual) if step<=3 else 0.0)


def rollback_feedback(best_feedback, applied_operations, candidate_distance, best_distance):
    """Keep rejection memory, not full prompts or stale rejected-page markup."""
    changes=[]; remaining=2400
    fields=('action','selector','name','value','css','javascript','html')
    for operation in applied_operations:
        change={field:str(operation[field])[:240] for field in fields if field in operation}
        truncated=[field for field in fields if field in operation and len(str(operation[field]))>240]
        if truncated: change['truncated_fields']=truncated
        encoded=json.dumps(change,ensure_ascii=False)
        if len(encoded)>remaining: break
        changes.append(change); remaining-=len(encoded)
    evidence={'rejected_gate_distance':candidate_distance,'retained_gate_distance':best_distance,
              'applied_changes':changes,'additional_changes_not_summarized':len(applied_operations)-len(changes)}
    return ('The previous attempt was rolled back. The current HTML and findings describe the retained best page, NOT the rejected page. '
            'Do not repeat these rejected changes; choose a different, narrowly scoped repair and continue recovering pending content/tasks. '
            'Rejected-attempt summary (long fields are explicitly abbreviated): '+json.dumps(evidence,ensure_ascii=False)
            +'\nPending feedback for the retained best page:\n'+best_feedback)
