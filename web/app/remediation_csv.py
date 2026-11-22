"""Read-only tabular export of recorded remediation measurements."""
import csv
from io import StringIO
import json

from axe_metrics import project_wcag
from accessibility_taxonomy.presentation import DIMENSIONS, failure_count
from remediation_report_presentation import retention_summary, best_measured, retained_candidate, iteration_ordinals
from remediation_interventions import policy_identifier


RUN_FIELDS = (
    'id', 'title', 'status', 'source_result_id', 'created_at', 'completed_at',
    'execution_mode', 'accessibility_priority', 'transformation_format',
    'generator_provider', 'generator_model', 'reviewer_provider', 'reviewer_model',
    'temperature', 'use_rag', 'use_wave', 'max_iterations', 'max_cost_usd',
    'max_execution_seconds', 'min_lighthouse', 'max_axe', 'min_aim',
    'accepted_iteration_id', 'total_input_tokens', 'total_output_tokens',
    'total_cost_usd', 'execution_seconds', 'progress_message', 'error_message',
)
MEASUREMENT_FIELDS = (
    'axe_issue_instances', 'axe_best_practice_issues', 'lighthouse_score',
    'wave_aim_score', 'dom_distance_percent', 'content_retention_percent',
    'text_retention_percent', 'links_retention_percent', 'images_retention_percent',
    'visual_similarity_percent',
)
FIELDS = tuple('run_' + name for name in RUN_FIELDS) + (
    'run_strategy', 'run_intervention_version',
    'source_experiment_id', 'source_url', 'source_name', 'source_evaluated_at',
    'imported', 'row_kind', 'iteration_id', 'iteration_number', 'is_retained',
    'is_best_measured', 'targets_met', 'measured_at', 'decision', 'decision_reason', 'generator_provider',
    'generator_model', 'reviewer_provider', 'reviewer_model',
) + (
    'experiment_role','proposal_document_status','raw_axe_issue_instances','raw_lighthouse_score',
    'source_axe_issue_instances','source_lighthouse_score','axe_reduction_percent','lighthouse_increase_percent',
) + MEASUREMENT_FIELDS + (
    'input_tokens', 'output_tokens', 'cost_usd', 'execution_seconds',
    'rag_used', 'rag_example_count', 'evidence_recovered',
    'intervention_version','wire_level','assigned_level','operation_level','worker_choice_id','policy_id','decision_id','retrieval_id','verification_id','technical_status',
    'taxonomy_curation_version','taxonomy_excluded_types_json','taxonomy_supplement_version','taxonomy_supplementary_evidence_json','taxonomy_version','taxonomy_status','taxonomy_assessment_id',
    'taxonomy_summary_json','taxonomy_comparison_json','taxonomy_measurement_cost_usd',
    'taxonomy_shared_baseline_cost_usd','taxonomy_inconclusive_count','taxonomy_outside_scope_count','taxonomy_coverage_json',
) + tuple('taxonomy_'+key+'_failures' for _,_,key in DIMENSIONS)


def _object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _cell(value):
    # Titles, URLs and diagnostic text are untrusted even in stored evidence.
    if isinstance(value, str) and (value.startswith(('\t', '\r', '\n')) or
                                  value.lstrip().startswith(('=', '+', '-', '@'))):
        return "'" + value
    return value


def remediation_csv(run, source, iterations):
    """Original plus each stored iteration; no source or candidate mutation."""
    best = best_measured(run,iterations)
    retained=retained_candidate(run,iterations)
    ordinals = iteration_ordinals(iterations)
    outcome=_object(run.get('harness_outcome_json'))
    taxonomy=_object(outcome.get('taxonomy_measurement'))
    strategies = [_object(item.get('strategy_json')) for item in iterations]
    common = {'run_' + name: run.get(name) for name in RUN_FIELDS}
    common.update(run_strategy=policy_identifier(run),
                  run_intervention_version=run.get('intervention_version'),
                  source_experiment_id=source.get('experiment_id'),
                  source_url=source.get('url'),
                  source_name=source.get('display_name') or source.get('page_title') or source.get('url'),
                  source_evaluated_at=source.get('evaluated_at'),
                  imported=bool(run.get('import_provenance_json')))
    if any(strategy.get('recovery') for strategy in strategies):
        common.update(run_total_input_tokens=None, run_total_output_tokens=None)

    original = project_wcag(source)
    if run.get('baseline_axe') is not None: original['axe_violations']=run['baseline_axe']
    if run.get('baseline_lighthouse') is not None:original['lighthouse_score']=run['baseline_lighthouse']
    outcome=_object(run.get('harness_outcome_json'))
    rows = [dict(common, row_kind='original', is_retained=bool(outcome.get('selected',{}).get('original')),
                 measured_at=source.get('evaluated_at'),
                 axe_issue_instances=original.get('axe_violations'),
                 axe_best_practice_issues=original.get('axe_best_practice_issues'),
                 lighthouse_score=original.get('lighthouse_score'),
                 wave_aim_score=original.get('wave_aim_score'))]
    for stored, strategy in zip(iterations, strategies):
        item = project_wcag(stored)
        recovery = bool(strategy.get('recovery'))
        retention = _object(strategy.get('content_retention'))
        selection = _object(strategy.get('candidate_selection'))
        rag = _object(strategy.get('rag'))
        retrieved = rag.get('retrieved')
        count = len(retrieved) if isinstance(retrieved, list) else None
        row = dict(common, row_kind='iteration', iteration_id=item.get('id'),
                   iteration_number=ordinals[item['id']],
                   is_best_measured=bool(best and item.get('id')==best['id']),
                   targets_met=None if run.get('max_axe') is None or run.get('min_lighthouse') is None else (item.get('axe_violations') is not None and item['axe_violations']<=run['max_axe'] and item.get('lighthouse_score') is not None and item['lighthouse_score']>=run['min_lighthouse']),
                   is_retained=(bool(retained and item.get('id')==retained.get('id'))
                                if outcome.get('selected') or run.get('accepted_iteration_id') is not None else None),
                   measured_at=item.get('created_at'), decision=item.get('decision'),
                   decision_reason=item.get('decision_reason'),
                   axe_issue_instances=item.get('axe_violations'),
                   axe_best_practice_issues=item.get('axe_best_practice_issues'),
                   lighthouse_score=item.get('lighthouse_score'),
                   wave_aim_score=item.get('wave_aim_score'),
                   dom_distance_percent=item.get('dom_distance'),
                   content_retention_percent=retention_summary(retention)['percent'],
                   text_retention_percent=retention.get('text_percent'),
                   links_retention_percent=retention.get('links_percent'),
                   images_retention_percent=retention.get('images_percent'),
                   visual_similarity_percent=selection.get('visual_similarity_percent'),
                   rag_used=bool(count) if count is not None else None,
                   rag_example_count=count, evidence_recovered=recovery)
        for name in ('generator_provider', 'generator_model', 'reviewer_provider', 'reviewer_model',
                     'input_tokens', 'output_tokens', 'cost_usd', 'execution_seconds'):
            row[name] = None if recovery and name in {
                'input_tokens', 'output_tokens', 'cost_usd', 'execution_seconds'} else item.get(name)
        harness=_object(strategy.get('harness'))
        row.update(intervention_version=strategy.get('intervention_version')or run.get('intervention_version'),wire_level=strategy.get('wire_level'),assigned_level=strategy.get('assigned_level'),operation_level=strategy.get('operation_level'),
            worker_choice_id=harness.get('worker_id'),policy_id=harness.get('policy_id'),decision_id=harness.get('decision_id'),
            retrieval_id=harness.get('retrieval_id'),verification_id=harness.get('verification_id'),technical_status=harness.get('assessment',{}).get('status'))
        rows.append(row)

    # Experiment observations are the actual proposals, including regressions.
    # Software retention never substitutes the baseline for a generated page.
    for row, strategy in zip(rows,[{},*strategies]):
        row.update(experiment_role='baseline'if row['row_kind']=='original'else'generated_proposal',
                   source_axe_issue_instances=original.get('axe_violations'),
                   source_lighthouse_score=original.get('lighthouse_score'))
        baseline=_object(strategy.get('baseline'))
        no_document=(baseline.get('evaluable') is False or
                     (baseline.get('evaluable') is not True and
                      (baseline.get('complete_document') is False or
                       'no unique complete HTML document' in str(baseline.get('output','')))))
        row.update(raw_axe_issue_instances=row.get('axe_issue_instances'),
                   raw_lighthouse_score=row.get('lighthouse_score'),
                   proposal_document_status='no_complete_document'if no_document else
                     'partial_document'if baseline.get('evaluable') is True and baseline.get('complete_document') is False else
                     'complete_document'if baseline.get('complete_document')is True else None)
        if no_document:
            # Historical prose may have a browser score. Keep it as raw
            # evidence but do not export it as an accessibility result.
            row.update(axe_issue_instances=None,lighthouse_score=None,targets_met=None)
        for key, metric, sign in (('axe_reduction_percent','axe_issue_instances',-1),
                                  ('lighthouse_increase_percent','lighthouse_score',1)):
            before=row.get('source_'+metric);after=row.get(metric)
            row[key]=sign*100*(after-before)/before if before and after is not None else None

    for row in rows:
        if row.get('proposal_document_status')=='no_complete_document':
            continue
        if row['row_kind']=='original':
            row['is_retained']=bool(outcome.get('selected',{}).get('original'))
            if row['is_retained'] and outcome.get('distance') == 0:
                row['dom_distance_percent']=0.0
        # Only the baseline and coordinator-retained result were assessed.
        # Rejected/intermediate candidates never inherit the final judgment.
        scope='original' if row['row_kind']=='original' else 'retained' if row.get('is_retained') else None
        if not scope or not taxonomy: continue
        row.update(taxonomy_curation_version=taxonomy.get('curation_version'),taxonomy_excluded_types_json=json.dumps(taxonomy.get('excluded_types',{})),taxonomy_version=taxonomy.get('version'),taxonomy_status=taxonomy.get('status'),
            taxonomy_assessment_id=taxonomy.get(scope+'_assessment_id'),
            taxonomy_supplement_version=taxonomy.get('supplement_version'),taxonomy_supplementary_evidence_json=json.dumps(taxonomy.get('supplementary_evidence_ids',[])),
            taxonomy_summary_json=json.dumps(taxonomy.get(scope),ensure_ascii=False) if taxonomy.get(scope) else None)
        categories=(taxonomy.get(scope) or {}).get('categories',{})
        coverage=(taxonomy.get('coverage_detail') or {}).get(scope)
        if coverage:
            row.update(taxonomy_inconclusive_count=coverage['inconclusive'],taxonomy_outside_scope_count=coverage['outside_scope'],taxonomy_coverage_json=json.dumps(coverage,ensure_ascii=False))
        for category,_,key in DIMENSIONS:
            row['taxonomy_'+key+'_failures']=failure_count(categories.get(category))
        if row.get('is_retained'):
            row.update(taxonomy_comparison_json=json.dumps(taxonomy.get('comparison'),ensure_ascii=False),
                taxonomy_measurement_cost_usd=taxonomy.get('measurement_cost_usd'),
                taxonomy_shared_baseline_cost_usd=taxonomy.get('shared_baseline_cost_usd'))

    if (not iterations and run.get('execution_mode') == 'single_shot'
            and outcome.get('output_evidence', {}).get('evaluable') is False):
        rows.append(dict(common, row_kind='unavailable_output',
            experiment_role='unavailable_output', proposal_document_status='response_unavailable',
            decision_reason=outcome.get('stop_reason'), is_retained=False,
            cost_usd=run.get('total_cost_usd'), execution_seconds=run.get('execution_seconds'),
            input_tokens=run.get('total_input_tokens'), output_tokens=run.get('total_output_tokens')))

    output = StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows({key: _cell(value) for key, value in row.items()} for row in rows)
    return '\ufeff' + output.getvalue()
