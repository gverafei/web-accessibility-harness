from dataclasses import dataclass
from bs4 import BeautifulSoup
"""Versioned intervention policies, independent of model tier and gate scores."""
from dataclasses import dataclass
from bs4 import BeautifulSoup


@dataclass(frozen=True)
class Approach:
    step: int
    name: str
    engine: str
    instruction: str
    reference: str
    max_operations: int
    version: str = "five-fixed-levels-v8"


APPROACHES = (
    Approach(1, "Minimal patches", "minimal_patch", "Only attributes, small insertions and narrowly scoped CSS. No element replacement, component substitution or layout restructuring.", "https://arxiv.org/abs/2608.24913", 20),
    Approach(2, "Localized repair", "localized_patch", "Repair individual defective elements. Small semantic replacements are allowed; never replace a whole navigation, section, form or content region.", "https://arxiv.org/html/2507.19549v1", 35),
    Approach(3, "Coordinated repair", "coordinated_patch", "Follow the planner's root-cause groups and dependencies. Coordinate HTML, scoped CSS and local keyboard behavior without redesigning the page or replacing its framework.", "https://arxiv.org/html/2606.21926v1", 60),
    Approach(4, "HTML regeneration", "regenerate_html", "Regenerate the complete page from full acquired HTML using the original whole-document prompt and optional Bootstrap structural reference. Retain the initial one-shot. Refine only with localized patches to the best regenerated page; roll back regressions.", "https://doi.org/10.3390/computers15060343", 35),
    Approach(5, "Markdown regeneration", "regenerate_markdown", "Regenerate the complete page from quality-checked Markdown using the same original whole-document prompt and optional Bootstrap structural reference. Retain the initial one-shot. Refine only with localized patches to the best regenerated page; roll back regressions.", "https://doi.org/10.3390/computers15060343", 35),
)










def refinement_approach(approach, whole_regeneration):
    """Keep localized edit bounds and the current regeneration permissions together."""
    if not whole_regeneration:
        return approach
    from dataclasses import replace
    from remediation_interventions import VERSION
    localized = APPROACHES[1]
    if approach.version != VERSION:
        return localized
    return replace(localized, name=approach.name + " local refinement",
                   engine=approach.engine, version=approach.version)


def constrain_plan(document, plan, approach, selected_selectors=(), base_url=None, context=None, *, destination_repairs=(), validation_version=None):
    """Enforce intervention scope independently of the model's persona."""
    if validation_version is not None:
        from coordinated_role_validation import SUPPORTED_VERSIONS
        if validation_version not in SUPPORTED_VERSIONS:
            raise ValueError('Unknown patch validation contract')
    soup = BeautifulSoup(document, "html.parser")
    accepted, rejected = [], []
    accepted_indexes=[];invalid_indexes=set(range(approach.max_operations,len(plan.get("operations")or[])))
    cause_errors={}
    if approach.engine=='structural_patch':
        for group in plan.get('root_causes',[]):
            for selector in group.get('selectors',[]):
                try:matched=bool(soup.select(selector))
                except Exception:matched=False
                if not matched:
                    for index in group.get('operation_indexes',[]):
                        cause_errors[index]='root cause contains an invalid or unmatched selector: '+selector
    rejected.extend({'operation':operation,'reason':'operation budget exceeded; split remaining targeted repairs across refinements'} for operation in (plan.get('operations') or [])[approach.max_operations:])
    for index,operation in enumerate((plan.get("operations") or [])[:approach.max_operations]):
        # An explicit selector plus declarations expresses the same requested
        # CSS operation. Materialize the rule before scope checks; never insert
        # bare declarations into STYLE or silently invent another repair.
        if operation.get('action')=='append_css' and isinstance(operation.get('css'),str) and not any(c in operation['css']for c in '{}'):
            operation={**operation,'css':str(operation.get('selector',''))+'{'+operation['css']+'}',
                       'css_input_representation':'selector-bound-declarations'}
        invalid_fields = [field for field in ('action','selector','name','tag','html','css','javascript')
                          if field in operation and not isinstance(operation[field], str)]
        if invalid_fields:
            invalid_indexes.add(index)
            rejected.append({'operation':operation,'reason':'patch fields must be strings: '+', '.join(invalid_fields)})
            continue
        if index in cause_errors:
            invalid_indexes.add(index)
            rejected.append({'operation':operation,'reason':cause_errors[index]})
            continue
        action = operation.get("action")
        selector = str(operation.get("selector") or "")
        reason = None
        if action=='wrap_element' and (approach.step==1 or operation.get('tag') not in {'ul','ol'}):
            reason='only localized or stronger repairs may add native list wrappers'
        if action=="append_javascript" and approach.step<3:
            reason="minimal/localized approaches do not rewrite behavior"
        if action in {"set_attribute","remove_attribute"} and approach.step<=2 and str(operation.get("name") or "").lower() in {"href","src","action","method","name","value","type","onclick","onchange"}:
            from harness.destination_repairs import permits
            if approach.step!=2 or not permits(soup,operation,destination_repairs):
                reason = "local repairs cannot change task destinations or control contracts"
        if action == "replace_element":
            if approach.step == 1:
                reason = "minimal patches forbid replacement"
            elif approach.step == 2:
                try:
                    nodes = soup.select(selector)
                    if any(node.name in {"nav", "main", "section", "article", "form", "header", "footer"} or len(node.find_all(True)) > 12 for node in nodes):
                        reason = "localized repair cannot replace a region"
                except Exception:
                    reason = "invalid selector"
            if not reason:
                from collections import Counter
                import re
                try:
                    originals=soup.select(selector)
                    replacement=BeautifulSoup(operation.get("html") or "","html.parser")
                    words=lambda node: Counter(re.findall(r"\w+",node.get_text(" ",strip=True).casefold()))
                    from urllib.parse import urljoin
                    resources=lambda node: {(element.name,key,urljoin(base_url or "",element.get(key)) if key!="name" else element.get(key)) for element in [node,*node.find_all(True)] for key in ("href","src","action","name") if element.get(key)}
                    for original in originals:
                        required=words(original)
                        retained=words(replacement)
                        if sum((required-retained).values())>max(1,sum(required.values())*.05): reason="replacement discards source text; keep the previous component"
                        if resources(original)-resources(replacement): reason="replacement discards destinations/assets/control names; keep the previous component"
                except Exception: reason="replacement contract could not be verified"
        if action == "append_css" and approach.step == 1:
            import re
            selectors = re.findall(r"([^{}]+)\{", operation.get("css") or "")
            if any(re.search(r"(^|[,\s])(body|html|\*)(?=[:,\s]|$)", value.strip()) for value in selectors):
                reason = "minimal patches forbid global CSS overrides"
        if not reason and approach.version in ('preservation-first-four-fixed-v1','two-patch-creative-regeneration-v2'):
            from remediation_patch_safety import rejection_reason
            from coordinated_role_validation import VERSION as COMPLETE_SUBTREE_VERSION
            reason = rejection_reason(document, operation, approach, base_url, context,
                                      complete_subtrees=validation_version == COMPLETE_SUBTREE_VERSION)
            if validation_version is not None and approach.engine == 'structural_patch':
                from coordinated_role_validation import (
                    LIST_ROLE_REJECTION, repairs_native_list_children)
                if (reason == LIST_ROLE_REJECTION
                        and repairs_native_list_children(document, plan, index)):
                    reason = None
        if reason:invalid_indexes.add(index)
        else:accepted_indexes.append(index)
        (rejected if reason else accepted).append({"operation":operation,"reason":reason} if reason else operation)
    groups=plan.get('root_causes',[])
    if approach.engine=='structural_patch' and rejected:
        # Preserve each verified cause atomically; unrelated causes do not
        # inherit a failure. Dependency closure prevents partial prerequisites.
        ids={g.get('id')for g in groups if isinstance(g,dict)}
        valid_groups=(approach.version=='two-patch-creative-regeneration-v2' and bool(groups)
            and all(isinstance(g,dict)and isinstance(g.get('operation_indexes'),list)and all(type(i)is int for i in g['operation_indexes'])and isinstance(g.get('depends_on'),list)and set(g['depends_on'])<=ids for g in groups)
            and sorted(i for g in groups for i in g['operation_indexes'])==list(range(len(plan['operations']))) and len(ids)==len(groups))
        if valid_groups:
            blocked={g['id']for g in groups if set(g['operation_indexes'])&invalid_indexes}
            while True:
                expanded=blocked|{g['id']for g in groups if set(g['depends_on'])&blocked}
                if expanded==blocked:break
                blocked=expanded
            blocked_indexes={i for g in groups if g['id']in blocked for i in g['operation_indexes']}
            kept=[];indexes=[]
            for index,op in zip(accepted_indexes,accepted):
                if index in blocked_indexes:rejected.append({'operation':op,'reason':'this root cause or a required dependency failed its scope guard'})
                else:kept.append(op);indexes.append(index)
            positions={old:new for new,old in enumerate(indexes)}
            groups=[{**g,'operation_indexes':[positions[i]for i in g['operation_indexes']]}for g in groups if g['id']not in blocked]
            accepted=kept
        else:
            rejected.extend({'operation':op,'reason':'coordination is atomic; another operation failed its scope guard'}for op in accepted)
            accepted=[]
    return {**plan, "operations":accepted,**({'root_causes':groups}if approach.engine=='structural_patch'else{})}, rejected


def approach_for(priority):
    step = next((index for index, threshold in enumerate((15, 35, 55, 75, 100)) if int(priority or 55) <= threshold), 4)
    return APPROACHES[step]

def presentation_priority(priority, strategy=None):
    """Classify known renderer versions without rewriting research history.

    Old protected-block pilots were submitted as step 5 before that engine
    moved to step 4. Their saved configuration remains unchanged.
    """
    if isinstance(strategy,dict):
        contract=strategy.get('born_content_contract') or {}
        version=contract.get('version') if isinstance(contract,dict) else None
        if version=='protected-blocks-v1': return 75
        if version=='protected-data-components-v2': return 90
    return priority

def presentation_name(priority, strategy=None):
    """Preserve historical engine identity when current slider labels change."""
    if isinstance(strategy,dict):
        version=(strategy.get('born_content_contract') or {}).get('version')
        if version=='protected-blocks-v1': return 'Content-preserving recomposition'
        if version=='protected-data-components-v2': return 'Born-accessible'
        regeneration=strategy.get('regeneration') or {}
        if regeneration.get('representation') in {'html','markdown'}:
            return 'HTML regeneration' if regeneration['representation']=='html' else 'Markdown regeneration'
    return approach_for(priority).name

def contrast_foreground(background):
    channels=[int(background[index:index+2],16)/255 for index in (1,3,5)]
    linear=[value/12.92 if value<=.04045 else ((value+.055)/1.055)**2.4 for value in channels]
    luminance=sum(weight*value for weight,value in zip((.2126,.7152,.0722),linear))
    black=(luminance+.05)/.05
    white=1.05/(luminance+.05)
    return '#000000' if black>=white else '#ffffff'


def dynamic_presentation(run, store):
    """Read the frozen condition, never infer dynamism from participant count."""
    import json
    try:
        config=json.loads(run.get('harness_config_json') or '{}')
        if not config.get('campaign_id'):return False
        conditions=store.get(config['campaign_id'])['data'].get('conditions',[])
        return len(conditions)==1 and conditions[0].get('level')==6
    except (ValueError,TypeError,KeyError,FileNotFoundError):
        return False
