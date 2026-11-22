"""Versioned public policies; historical wire IDs are never renumbered."""
from dataclasses import dataclass, replace
import json
from bs4 import BeautifulSoup
from remediation_approaches import APPROACHES

VERSION = 'two-patch-creative-regeneration-v2'
PRESERVATION_VERSION = 'preservation-first-four-fixed-v1'
LEGACY_VERSION = 'five-fixed-levels-v8'


@dataclass(frozen=True)
class Policy:
    level: int
    wire_level: int
    priority: int
    name: str
    engine: str
    instruction: str

    def approach(self, version=VERSION):
        original=APPROACHES[self.wire_level-1]
        return replace(original,name=self.name,engine=self.engine,instruction=self.instruction,version=version)


PRESERVATION_POLICIES = (
    Policy(1,1,15,'Minimal patches','minimal_patch',
        'Preserve original nodes, layout, CSS and native tasks. Correct only attributes, small adjunct labels/descriptions and targeted contrast/focus rules. '
        'No replacement, wrapping, behavior rewriting, global CSS or structure/layout changes. Leave defects outside this scope unresolved.'),
    Policy(2,3,55,'Structural and coordinated repair','structural_patch',
        'Repair semantic structure within observed components and coordinate related patches by verified root cause. '
        'Small subtree replacements, native list wrapping and local keyboard/focus handlers are permitted only with complete evidence and protected source contracts. '
        'Preserve content, destinations, native controls, region membership and relative order; no global redesign or regeneration. '
        'Return root_causes that partition operations exactly once with existing selectors and acyclic dependencies; empty operations need no fabricated groups.'),
    Policy(3,4,75,'HTML regeneration','regenerate_html',
        'Regenerate complete HTML from the complete admitted original HTML, recorded content/task inventory, structural outline and original capture. '
        'Preserve original information architecture, region order, media grouping, visual identity and native contracts before optimizing accessibility. '
        'No imposed replacement framework or generic template. Refine locally on the best admissible regenerated candidate; roll back regressions.'),
    Policy(4,5,90,'Markdown regeneration','regenerate_markdown',
        'Regenerate complete HTML from verified Markdown of the same admitted source, supplemented by exact source structure, media and native-task contracts and original capture. '
        'Preserve original region hierarchy, ordering, visual identity and tasks before optimizing accessibility. '
        'Do not turn controls into decoration or the page into a generic reading view. Refine locally on the best admissible candidate.'),
)
POLICIES = (*PRESERVATION_POLICIES[:2],
    replace(PRESERVATION_POLICIES[2],instruction='Create a new polished, accessible and useful page from the HTML source and its purpose, category, URL, description and reference capture. '
        'Choose composition, typography, colors and layout freely; no prescribed template or framework. Fidelity and omitted source elements are measured, not acceptance gates. '
        'Use functional native controls and available resources; the candidate must pass its own observable functional and visual checks.'),
    replace(PRESERVATION_POLICIES[3],instruction='Create a new polished, accessible and useful page from Markdown and its purpose, category, URL, description and reference capture. '
        'Choose composition, typography, colors and layout freely; no prescribed template or framework. Fidelity and omitted source elements are measured, not acceptance gates. '
        'Use functional native controls and available resources; the candidate must pass its own observable functional and visual checks.'))
WIRES = tuple(p.wire_level for p in POLICIES)
DYNAMIC_WIRE = 6
DYNAMIC_LEVEL = 5


def validate_version(version):
    if version not in (VERSION,PRESERVATION_VERSION,LEGACY_VERSION):
        raise ValueError('Unknown intervention contract version')
    return version


def public_to_wire(level):
    if type(level)is not int or level not in range(1,DYNAMIC_LEVEL+1):
        raise ValueError('Choose one of the four fixed policies or dynamic selection')
    return DYNAMIC_WIRE if level==DYNAMIC_LEVEL else POLICIES[level-1].wire_level


def wire_to_public(level):
    if type(level)is not int:raise ValueError("Intervention ID must be an integer")
    if level==DYNAMIC_WIRE:return DYNAMIC_LEVEL
    policy=next((p for p in POLICIES if p.wire_level==level),None)
    if not policy:raise ValueError('Intervention is not in the current four-policy contract')
    return policy.level


def approach(level, version=LEGACY_VERSION):
    validate_version(version)
    if version==LEGACY_VERSION:return APPROACHES[level-1]
    policies=PRESERVATION_POLICIES if version==PRESERVATION_VERSION else POLICIES
    policy=next((p for p in policies if p.wire_level==level),None)
    if not policy:raise ValueError('Intervention is not in the current four-policy contract')
    return policy.approach(version)


def active_wires(manifest):
    version=manifest.get('intervention_version',LEGACY_VERSION)
    validate_version(version)
    return WIRES if version in (VERSION,PRESERVATION_VERSION) else tuple(range(1,6))


def creative_regeneration(version, wire_level):
    return version==VERSION and wire_level in (4,5)


def four_policy(version):
    return version in (VERSION,PRESERVATION_VERSION)


def skill_manifest(version):
    if version == VERSION:
        return 'manifest-four-fixed-v3.json'
    return 'manifest-four-fixed-v1.json'


def _coordination_mismatch_feedback(mismatches):
    """Report literal assignments, without guessing intended causes or edits."""
    def bounded(value):
        text = str(value)
        return text if len(text) <= 180 else text[:180] + ' [truncated]'

    rows = [
        {'group': bounded(group_id), 'operation_index': index,
         'actual_operation_selector': bounded(selector)}
        for group_id, index, selector in mismatches[:8]
    ]
    return (
        'Operation selector is not covered by its root cause. '
        'coordination-feedback-v1: ' + json.dumps(rows, ensure_ascii=True) +
        f'. {len(mismatches)} mismatched assignments in total. '
        'Indexes are zero-based positions in the final operations array. '
        'Rebuild operation_indexes after all insertions/removals; check every group '
        'against that final array. Assign each operation exactly once to its intended '
        'cause and list its exact selector there. Do not broaden a cause merely to '
        'silence this check. No operation from this proposal was applied.'
    )


def coordinated_plan(document, plan):
    """Validate a graph before executing any structural-policy operation."""
    if not isinstance(plan,dict)or not isinstance(plan.get('operations'),list)or any(not isinstance(op,dict)for op in plan['operations']):
        raise ValueError('Patch output requires an operations array of objects')
    operations=plan['operations'];groups=plan.get('root_causes',[])
    if len(operations)>60:raise ValueError('Structural repair exceeds its 60-operation contract')
    if not operations:
        if groups:raise ValueError('An empty patch cannot reference operations')
        return {**plan,'root_causes':[]}, {'version':'root-cause-dag-v1','groups':[],'operation_order':[]}
    if not isinstance(groups,list)or not groups or len(groups)>60:
        raise ValueError('Structural repair requires bounded root-cause groups')
    by_id={};assigned=[];mismatches=[]
    for group in groups:
        if not isinstance(group,dict)or not isinstance(group.get('id'),str)or not group['id']or group['id']in by_id:
            raise ValueError('Root causes require distinct nonempty IDs')
        selectors=group.get('selectors');deps=group.get('depends_on');indexes=group.get('operation_indexes')
        if not isinstance(selectors,list)or not selectors or any(not isinstance(s,str)or not s for s in selectors):
            raise ValueError('Root causes require observed selectors')
        if not isinstance(deps,list)or any(not isinstance(dep,str)for dep in deps):
            raise ValueError('Root-cause dependencies must be typed IDs')
        if not isinstance(indexes,list)or not indexes or any(type(i)is not int or not 0<=i<len(operations)for i in indexes):
            raise ValueError('Root causes require valid operation indexes')
        # Validate graph structure here. Selector applicability belongs to the
        # per-cause scope guard, so one stale selector cannot discard unrelated
        # verified repairs. Malformed partitions/dependencies still fail closed.
        mismatches.extend(
            (group['id'], index, operations[index].get('selector'))
            for index in indexes if operations[index].get('selector') not in selectors
        )
        assigned.extend(indexes);by_id[group['id']]=group
    if mismatches:
        raise ValueError(_coordination_mismatch_feedback(mismatches))
    if sorted(assigned)!=list(range(len(operations))):
        raise ValueError('Root causes must partition all operations exactly once')
    ordered=[];completed=set()
    while len(completed)<len(groups):
        ready=[g for g in groups if g['id']not in completed and set(g['depends_on'])<=completed]
        if not ready:raise ValueError('Unknown or cyclic root-cause dependency')
        for group in ready:ordered.extend(group['operation_indexes']);completed.add(group['id'])
    positions={original:index for index,original in enumerate(ordered)}
    executable_groups=[{**group,'operation_indexes':[positions[i]for i in group['operation_indexes']]}for group in groups]
    return {**plan,'operations':[operations[i]for i in ordered],'root_causes':executable_groups}, {
        'version':'root-cause-dag-v3','groups':groups,'operation_order':ordered,'executable_groups':executable_groups}


def presentation(run, strategy=None):
    """Project current labels without changing legacy recorded identifiers."""
    from remediation_approaches import approach_for
    if run.get('execution_mode') == 'single_shot':
        return {'presentation_name': 'Zero-shot, single-pass HTML remediation',
                'presentation_level': None, 'preservation_filter': 'zero-shot'}
    strategy=strategy or {}
    version=strategy.get('intervention_version')or run.get('intervention_version',LEGACY_VERSION)
    current=four_policy(version)
    priority=run.get('presentation_priority',run.get('accessibility_priority',15))
    if not current:
        return {'preservation_filter':str(priority),'presentation_level':{15:1,35:2,55:3,75:4,90:5,105:6}.get(priority)}
    level=DYNAMIC_LEVEL if run.get('dynamic_level') else wire_to_public(approach_for(priority).step)
    return {'presentation_name':'Dynamic harness'if level==DYNAMIC_LEVEL else POLICIES[level-1].name,
            'presentation_level':level,'preservation_filter':'current-'+str(105 if level==DYNAMIC_LEVEL else priority)}


def policy_identifier(run):
    """Run policy, distinct from the intervention selected for an iteration."""
    if run.get('execution_mode') == 'single_shot':
        return 'P0'
    if run.get('dynamic_level'):
        return 'P5'
    level = presentation(run).get('presentation_level')
    if level is None:
        return None
    prefix = 'P' if four_policy(run.get('intervention_version', LEGACY_VERSION)) else 'legacy-'
    return prefix + str(level)
