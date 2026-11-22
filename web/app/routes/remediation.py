import os
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import current_app, Blueprint, Response, flash, redirect, render_template, request, send_file, url_for, stream_with_context, jsonify, abort
from flask_babel import gettext as _, get_locale

from database import get_connection
from axe_metrics import project_wcag
from remediation_taxonomy import axe_taxonomy
from remediation_rag import status as rag_status
from settings import get_settings
from remediation_recipes import automatic_recipe, common_conditions
from remediation_model_choices import model_choices, model_choice, frozen_model_configuration, run_model_presentation
from remediation_approaches import presentation_priority, presentation_name, dynamic_presentation
from remediation_control_copy import control_copy
from remediation_report_presentation import iteration_presentation, event_presentation, decision_activity_events, best_measured, target_presentation, retained_summary, retained_candidate, failure_category, progress_presentation, retained_progress, live_loop_participants, live_provider_activity
from remediation_portability import export_manifest
from remediation_csv import remediation_csv
from remediation_report_presentation import iteration_ordinals, execution_counts
from warp_export import file_archive_chunks


remediation_bp = Blueprint("remediation", __name__, url_prefix="/remediation")
from accessibility_taxonomy.presentation import counts as taxonomy_counts
remediation_bp.add_app_template_filter(taxonomy_counts,'taxonomy_counts')
from accessibility_taxonomy.presentation import details as taxonomy_detail_rows
remediation_bp.add_app_template_filter(taxonomy_detail_rows,'taxonomy_details')
DATASET_ROOT = Path(os.getenv("DATASET_ROOT", "/datasets"))
PAGE_TYPES = ("homepage", "form", "search", "article", "product", "authentication", "listing", "media")
def available_llm_options(settings=None):
    settings = settings or get_settings()
    return model_choices(settings) if settings.get("openrouter_api_key") and settings.get("openrouter_base_url") else []



def now_local():
    return datetime.now(ZoneInfo(get_settings()["app_timezone"])).replace(tzinfo=None)


def remediation_download(run_ids):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        exported_at = now_local()
        payload, members = export_manifest(cursor, run_ids, exported_at.isoformat(), dataset_root=DATASET_ROOT)
    except (ValueError, OSError) as error:
        flash(str(error), 'warning')
        return redirect(url_for('remediation.runs'))
    finally:
        cursor.close(); conn.close()
    name = (f'remediation-{payload["runs"][0]["data"]["id"]}' if len(payload['runs']) == 1
            else f'remediations-{exported_at:%Y%m%d-%H%M%S}')
    return Response(file_archive_chunks('remediation.json', payload, members),
        mimetype='application/vnd.warp+zip',
        headers={'Content-Disposition': f'attachment; filename="{name}.warp"'})


@remediation_bp.get('/<int:run_id>/export')
def export_run(run_id):
    return remediation_download([run_id])


@remediation_bp.get('/<int:run_id>/trace.json')
def download_run_trace(run_id):
    """Full recorded technical trace; display summaries never replace evidence."""
    from harness.store import Store
    conn=get_connection(); cursor=conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT * FROM remediation_runs WHERE id=%s',(run_id,)); run=cursor.fetchone()
        if not run:return Response(status=404)
        cursor.execute('SELECT * FROM remediation_iterations WHERE run_id=%s ORDER BY iteration_number',(run_id,)); iterations=cursor.fetchall()
        cursor.execute('SELECT * FROM remediation_events WHERE run_id=%s ORDER BY id',(run_id,)); events=cursor.fetchall()
    finally:
        cursor.close(); conn.close()
    store=Store(current_app.config.get('HARNESS_ROOT')); calls=[]
    revisions=[];correction_archives=[]
    try:
        config=json.loads(run.get('harness_config_json')or'{}')
        revisions=[record for kind in ('taxonomy_measurement_revision','retention_revision','source_fidelity_revision','selection_review_revision','iteration_accounting_revision')for record in store.list(kind,config.get('campaign_id'))if (record['data'].get('outcome',{}).get('run_id')or record['data'].get('run_id'))=='sql-run-'+str(run_id)]if config.get('campaign_id')else[]
        archive_ids={r['data']['sql_archive_id']for r in revisions if r['data'].get('sql_archive_id')}
        correction_archives=[store.get(ident)for ident in archive_ids]
        iteration_ids={item['id']for item in iterations}
        if config.get('campaign_id'):
            correction_archives += [r for r in store.list('presentation_revision',config['campaign_id'])if r['data'].get('iteration_id')in iteration_ids]
    except (ValueError,TypeError):pass
    with store.connect() as db:
        if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='calls'").fetchone():
            calls=[dict(row) for row in db.execute('SELECT * FROM calls WHERE run=? ORDER BY created,id',('sql-run-'+str(run_id),))]
            seen={call['id']for call in calls}
            for revision in revisions:
                data=revision['data']
                if not data.get('measurement_campaign_id'):continue
                for row in db.execute('SELECT * FROM calls WHERE campaign=? AND run=? ORDER BY created,id',(data['measurement_campaign_id'],data.get('measurement_run_id')or data.get('outcome',{}).get('run_id'))):
                    if row['id']not in seen:calls.append(dict(row));seen.add(row['id'])
    for call in calls:
        for key in ('request_id','response_id'):
            if call.get(key):
                try:
                    record=store.get(call[key]);call[key.removesuffix('_id')]=json.loads(store.read_blob(call[key])) if key=='response_id' else record['data']
                except (KeyError,ValueError,OSError):call[key.removesuffix('_id')]={'missing':True}
    model_calls=[]
    from remediation_report_presentation import load_model_calls
    for item in iterations:
        try:strategy=json.loads(item.get('strategy_json') or '{}')
        except (TypeError,ValueError):strategy={}
        model_calls.append({'iteration_id':item['id'],'calls':load_model_calls(strategy,run_id,DATASET_ROOT)})
    return Response(json.dumps({'run':run,'iterations':iterations,'events':events,'provider_calls':calls,'model_calls':model_calls,'revisions':revisions,'correction_archives':correction_archives},default=str,ensure_ascii=False),mimetype='application/json',headers={'Content-Disposition':f'attachment; filename="remediation-{run_id}-trace.json"'})


@remediation_bp.get('/<int:run_id>/csv')
def download_run_csv(run_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT * FROM remediation_runs WHERE id=%s', (run_id,))
        run = cursor.fetchone()
        if not run:
            return Response(status=404)
        cursor.execute('SELECT * FROM experiment_results WHERE id=%s', (run['source_result_id'],))
        source = cursor.fetchone()
        if not source:
            return Response(status=404)
        cursor.execute('SELECT * FROM remediation_iterations WHERE run_id=%s ORDER BY iteration_number', (run_id,))
        iterations = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
    from harness.store import Store
    run['dynamic_level'] = dynamic_presentation(run, Store(current_app.config.get('HARNESS_ROOT')))
    return Response(remediation_csv(run, source, iterations), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="remediation-{run_id}.csv"',
                             'Cache-Control': 'no-store'})


@remediation_bp.route('/export', methods=['GET', 'POST'])
def export_runs():
    if request.method == 'POST':
        try:
            ids = [int(value) for value in request.form.getlist('run_ids')]
        except ValueError:
            flash(_('Invalid remediation selection.'), 'warning')
            return redirect(url_for('remediation.runs'))
        return remediation_download(ids)
    # Keep old bookmarks usable, without a separate selection screen.
    return redirect(url_for('remediation.runs'))


def source_snapshot(row):
    if row.get("response_source_path") and Path(row["response_source_path"]).is_file():
        return row["response_source_path"]
    if row.get("source_snapshot_path") and Path(row["source_snapshot_path"]).is_file():
        return row["source_snapshot_path"]
    if row.get("storage_key") and row.get("relative_path"):
        path = DATASET_ROOT / row["storage_key"] / row["relative_path"]
        if path.is_file():
            return str(path)
    return None


def improvement_metrics(original_axe, remediated_axe, original_lighthouse, remediated_lighthouse):
    """Return comparable percentage outcomes without hiding each metric's scale."""
    axe_percent=None
    if original_axe is not None and remediated_axe is not None:
        original=float(original_axe); remediated=float(remediated_axe)
        axe_percent=(100.0*(original-remediated)/original) if original else (0.0 if remediated == 0 else None)
    lighthouse_points=None; lighthouse_headroom=None
    if original_lighthouse is not None and remediated_lighthouse is not None:
        original=float(original_lighthouse); remediated=float(remediated_lighthouse)
        lighthouse_points=remediated-original
        lighthouse_headroom=(100.0*lighthouse_points/(100.0-original)) if original < 100 else (0.0 if lighthouse_points == 0 else None)
    return {"axe_percent":axe_percent,"lighthouse_points":lighthouse_points,"lighthouse_headroom_percent":lighthouse_headroom}


def global_lighthouse_metrics(rows):
    """Aggregate every terminal run that produced a candidate evaluation."""
    pairs=[(float(row["original_lighthouse"]),float(row["result_lighthouse"])) for row in rows if row.get("original_lighthouse") is not None and row.get("result_lighthouse") is not None]
    headroom=sum(100-original for original,_ in pairs)
    gain=sum(result-original for original,result in pairs)
    return {
        "headroom_percent":100*gain/headroom if headroom else (0.0 if pairs and gain == 0 else None),
        "average_gain":sum(result-original for original,result in pairs)/len(pairs) if pairs else None,
    }

def page_type_signals(snapshot_path):
    content=Path(snapshot_path).read_text(encoding="utf-8",errors="replace").lower()
    scores={"form":len(re.findall(r"<(form|input|select|textarea)\b",content)),"search":len(re.findall(r"(type=[\"']search|role=[\"']search|<search\b)",content))*3,"article":len(re.findall(r"<(article|time)\b",content))*2,"product":len(re.findall(r"(add.to.cart|itemprop=[\"']price|product)",content)),"authentication":len(re.findall(r"(type=[\"']password|autocomplete=[\"'](current-password|username))",content))*3,"listing":len(re.findall(r"(<ol\b|pagination|filter)",content)),"media":len(re.findall(r"<(video|audio|track)\b",content))*3,"homepage":len(re.findall(r"<(nav|header|footer)\b",content))}
    # Specific interaction/page-purpose signals are more diagnostic than generic
    # elements such as forms or timestamps. This avoids classifying a search page
    # as an article merely because its results contain several <time> elements.
    if scores["authentication"]:
        page_type="authentication"
    elif scores["search"]:
        page_type="search"
    elif scores["product"] >= 2:
        page_type="product"
    elif scores["media"]:
        page_type="media"
    elif scores["listing"] >= 2:
        page_type="listing"
    elif scores["homepage"] >= 3:
        page_type="homepage"
    elif scores["form"] >= 3:
        page_type="form"
    elif scores["article"] >= 2:
        page_type="article"
    else:
        page_type="homepage"
    return page_type,scores,content


def classified_page_type(snapshot_path):
    return page_type_signals(snapshot_path)[0]


@remediation_bp.get("/")
def runs():
    live_ids = None
    if 'live_ids' in request.args:
        values = request.args['live_ids'].split(',')
        if not 1 <= len(values) <= 50 or any(not value.isdecimal() or len(value) > 10 for value in values):
            return Response('Invalid run identifiers', status=400)
        live_ids = tuple(dict.fromkeys(int(value) for value in values))
    where = 'WHERE rr.id IN (' + ','.join(['%s'] * len(live_ids)) + ')' if live_ids else ''
    conn=get_connection(); cursor=conn.cursor(dictionary=True)
    try:
        cursor.execute("""SELECT rr.id,rr.source_result_id,rr.title,rr.status,rr.created_at,rr.generator_model,rr.model_cost_tier,
            rr.model_config_json,rr.harness_config_json,rr.intervention_version,
            rr.execution_mode,rr.accessibility_priority,rr.template_selection,
            rr.transformation_format,rr.progress_message,rr.progress_percent,
            rr.review_policy,rr.max_axe,rr.min_lighthouse,rr.min_aim,
            rr.accepted_iteration_id,rr.total_cost_usd,rr.execution_seconds,
            rr.import_provenance_json,rr.error_message,
            CASE WHEN JSON_VALID(rr.harness_outcome_json) THEN JSON_OBJECT(
                'selected',JSON_EXTRACT(rr.harness_outcome_json,'$.selected'),
                'axe',JSON_EXTRACT(rr.harness_outcome_json,'$.axe'),
                'lighthouse',JSON_EXTRACT(rr.harness_outcome_json,'$.lighthouse'))
                ELSE NULL END harness_outcome_json, r.url source_url,
            CASE WHEN e.source_type='local_html' THEN COALESCE(r.display_name,o.display_name,o.observation_key)
                 ELSE COALESCE(r.display_name,r.captured_url,r.url) END source_name,
            COALESCE(rr.baseline_axe,r.axe_wcag_violations) original_axe,COALESCE(rr.baseline_lighthouse,r.lighthouse_score) original_lighthouse,r.wave_aim_score original_aim,
            (SELECT COUNT(*) FROM remediation_iterations measured
             WHERE measured.run_id=rr.id
             AND measured.iteration_number<=accepted.iteration_number) retained_iteration_number,
            accepted.output_path retained_output_path,
            accepted.axe_wcag_violations remediated_axe,
            accepted.lighthouse_score remediated_lighthouse,
            accepted.wave_aim_score remediated_aim,
            accepted.dom_distance remediated_dom_distance,
            CASE WHEN JSON_VALID(accepted.strategy_json) THEN JSON_OBJECT(
                'intervention_version',JSON_EXTRACT(accepted.strategy_json,'$.intervention_version'),
                'born_content_contract',JSON_EXTRACT(accepted.strategy_json,'$.born_content_contract'),
                'regeneration',JSON_OBJECT('representation',JSON_EXTRACT(accepted.strategy_json,'$.regeneration.representation')),
                'content_retention',JSON_EXTRACT(accepted.strategy_json,'$.content_retention'))
                ELSE NULL END accepted_strategy_json,
            latest.axe_wcag_violations latest_axe,
            latest.lighthouse_score latest_lighthouse,
            latest.wave_aim_score latest_aim,
            latest.dom_distance latest_dom_distance,
            latest.generator_model actual_generator_model,
            CASE WHEN JSON_VALID(latest.strategy_json) THEN JSON_OBJECT(
                'intervention_version',JSON_EXTRACT(latest.strategy_json,'$.intervention_version'),
                'born_content_contract',JSON_EXTRACT(latest.strategy_json,'$.born_content_contract'),
                'regeneration',JSON_OBJECT('representation',JSON_EXTRACT(latest.strategy_json,'$.regeneration.representation')),
                'content_retention',JSON_EXTRACT(latest.strategy_json,'$.content_retention'))
                ELSE NULL END latest_strategy_json,
            r.evaluated_at source_evaluated_at,e.title source_experiment,e.source_type,
            EXISTS(SELECT 1 FROM remediation_iterations rag_iteration WHERE rag_iteration.run_id=rr.id
                AND JSON_LENGTH(JSON_EXTRACT(rag_iteration.strategy_json,'$.rag.retrieved')) > 0) rag_used,
            (SELECT re.actor FROM remediation_events re WHERE re.run_id=rr.id ORDER BY re.id DESC LIMIT 1) latest_actor
            FROM remediation_runs rr JOIN experiment_results r ON r.id=rr.source_result_id
            JOIN experiments e ON e.id=r.experiment_id
            LEFT JOIN dataset_observations o ON o.id=r.dataset_observation_id
            LEFT JOIN remediation_iterations accepted ON accepted.id=rr.accepted_iteration_id
            LEFT JOIN remediation_iterations latest ON latest.id=(SELECT ri.id FROM remediation_iterations ri WHERE ri.run_id=rr.id AND ri.axe_wcag_violations IS NOT NULL AND ri.lighthouse_score IS NOT NULL ORDER BY (GREATEST(COALESCE(ri.axe_wcag_violations,999999)-rr.max_axe,0)+GREATEST(rr.min_lighthouse-COALESCE(ri.lighthouse_score,0),0)) ASC,ri.axe_wcag_violations ASC,ri.lighthouse_score DESC,ri.iteration_number ASC LIMIT 1)
            """ + where + " ORDER BY rr.id DESC", live_ids or ())
        histories=cursor.fetchall()
        participation_where = 'WHERE run_id IN (' + ','.join(['%s'] * len(live_ids)) + ')' if live_ids else ''
        cursor.execute("SELECT id,run_id,iteration_number,axe_wcag_violations,lighthouse_score,generator_model,reviewer_model,agent_usage_json,JSON_UNQUOTE(JSON_EXTRACT(strategy_json,'$.assigned_level')) assigned_level FROM remediation_iterations " + participation_where, live_ids or ())
        participation={}
        applied_levels={}
        executed_iterations={}
        policies={row['id']:row.get('review_policy') for row in histories}
        # Keep large usage JSON out of MySQL's filesort buffer.
        iteration_rows = cursor.fetchall()
        for iteration in sorted(iteration_rows, key=lambda item: (item['run_id'],item['iteration_number'])):
            if iteration.get('axe_wcag_violations') is not None and iteration.get('lighthouse_score') is not None:
                executed_iterations[iteration['run_id']]=executed_iterations.get(iteration['run_id'],0)+1
            try:
                level=iteration.get('assigned_level')
                if level not in (None,'null'):applied_levels.setdefault(iteration['run_id'],[]).append(str(level))
            except (ValueError,TypeError):pass
            roles=participation.setdefault(iteration['run_id'],{})
            try: usage=json.loads(iteration.get('agent_usage_json') or '[]')
            except (ValueError,TypeError): usage=[]
            if not isinstance(usage,list): usage=[]
            if not usage:
                usage=[{'model':iteration.get('generator_model'),'role':'Generator'}]
                if policies.get(iteration['run_id']) != 'automated':
                    usage.append({'model':iteration.get('reviewer_model'),'role':'Coordinator'})
            for entry in usage:
                if not isinstance(entry,dict): continue
                model=entry.get('model')
                if model and not model.startswith('system/'):
                    roles.setdefault(model,set()).add(entry.get('role') or 'Agent')
        from harness.store import Store
        from remediation_listing import CampaignReader, hydrate_search
        listing_store = Store(current_app.config.get('HARNESS_ROOT'))
        presentation_store = CampaignReader(listing_store, histories)
        hydrate_search(histories, iteration_rows, listing_store)
        for row in histories:
            row['display_progress_message']=progress_presentation(row.get('progress_message'),_)
            row['executed_iterations']=executed_iterations.get(row['id'],0)
            row['participants']=[]
            row['model_presentation']=run_model_presentation(row)
            recorded={}
            try:
                recorded=json.loads(row.get('accepted_strategy_json') or row.get('latest_strategy_json') or '{}')
                row['presentation_priority']=presentation_priority(row.get('accessibility_priority'),recorded)
                row['presentation_name']=presentation_name(row.get('accessibility_priority'),recorded)
            except (ValueError,TypeError):
                row['presentation_priority']=row.get('accessibility_priority')
            row['dynamic_level']=dynamic_presentation(row,presentation_store)
            if row['dynamic_level']:
                row['presentation_name']='Dynamic harness'
                row['applied_levels']=' → '.join(applied_levels.get(row['id'],[]))
                row['presentation_priority']=105
            from remediation_interventions import presentation
            row.update(presentation(row,recorded))
            for model,roles in participation.get(row['id'],{}).items():
                concise_roles=set()
                for role in roles:
                    if 'reconstruction' in role.lower():
                        concise_roles.add(_('Reconstruction agent'))
                    elif 'architecture' in role.lower() or 'planning' in role.lower():
                        concise_roles.add(_('Architecture planning specialist'))
                    else:
                        concise_roles.add(_(role.split(' · ',1)[0]))
                row['participants'].append({'model':model,'roles':', '.join(sorted(concise_roles))})
    finally:
        try: cursor.close()
        finally: conn.close()
    completed=[row for row in histories if row["status"] not in {"queued","running"}]
    accepted=[row for row in histories if row["status"] in {"accepted","completed_with_warnings"}]
    for row in histories:
        try:outcome=json.loads(row.get('harness_outcome_json') or 'null') or {}
        except (ValueError,TypeError):outcome={}
        row['taxonomy_measurement']=outcome.get('taxonomy_measurement')
        row['review_candidate_available'] = bool(row.get('retained_output_path')
            and not outcome.get('selected', {}).get('original')
            and row.get('status') not in ('queued', 'running'))
        result=(outcome.get('axe'),outcome.get('lighthouse'),None) if outcome.get('selected') else (row.get('remediated_axe'),row.get('remediated_lighthouse'),row.get('remediated_aim'))
        row['result_axe'],row['result_lighthouse'],row['result_aim']=result
        if row.get('execution_mode')=='single_shot':
            from remediation_output_format import recorded_output_format
            row['recorded_output_format']=recorded_output_format(row.get('retained_output_path'),row['id'],DATASET_ROOT)
        row['display_progress_message']=retained_progress(row,row.get('retained_iteration_number'),result[0],result[1],_)
        if row.get('accepted_iteration_id') is not None and row.get('retained_iteration_number') is not None:
            row['latest_actor']='Acceptance coordinator'
        row['failure_category']=failure_category(row)
        row["improvement"]=improvement_metrics(row.get("original_axe"),row.get("result_axe"),row.get("original_lighthouse"),row.get("result_lighthouse"))
    if live_ids is not None:
        from remediation_listing import hydrate_taxonomy
        hydrate_taxonomy(histories, get_connection)
        response = Response(render_template('_remediation_history_rows.html', runs=histories), mimetype='text/html')
        response.headers['Cache-Control'] = 'no-store'
        return response
    axe_pairs=[(float(row["original_axe"]),float(row["remediated_axe"])) for row in accepted if row["original_axe"] is not None and row["remediated_axe"] is not None]
    lighthouse_summary=global_lighthouse_metrics(completed)
    aim_gains=[float(row["remediated_aim"])-float(row["original_aim"]) for row in accepted if row.get("original_aim") is not None and row["remediated_aim"] is not None]
    dom_values=[float(row["remediated_dom_distance"]) for row in accepted if row.get("remediated_dom_distance") is not None]
    from remediation_report_presentation import retention_summary
    retention=[]
    for row in accepted:
        try:
            strategy = json.loads(row.get("accepted_strategy_json") or "{}")
            evidence = strategy.get('content_retention') or (strategy.get('source_fidelity') or {}).get('retention')
            value = retention_summary(evidence)['percent']
            if value is not None:
                retention.append(value)
        except (ValueError, TypeError, AttributeError):
            pass
    axe_original=sum(pair[0] for pair in axe_pairs)
    axe_remediated=sum(pair[1] for pair in axe_pairs)
    summary={"total":len(histories),"active":sum(row["status"] in {"queued","running"} for row in histories),"accepted":len(accepted),"completed":len(completed),"cost":sum(float(row["total_cost_usd"] or 0) for row in histories),"axe_original_total":axe_original,"axe_remediated_total":axe_remediated,"axe_removed_total":axe_original-axe_remediated,"axe_improvement_percent":100*(axe_original-axe_remediated)/axe_original if axe_original else None,"lighthouse_headroom_percent":lighthouse_summary["headroom_percent"],"average_lighthouse_gain":lighthouse_summary["average_gain"],"average_aim_gain":sum(aim_gains)/len(aim_gains) if aim_gains else None,"average_dom":sum(dom_values)/len(dom_values) if dom_values else None,"average_retention":sum(retention)/len(retention) if retention else None}
    from summary_metrics import observed_reducer_rankings
    measured_axe = [float(row['result_axe']) for row in accepted if row.get('result_axe') is not None]
    measured_lighthouse = [float(row['result_lighthouse']) for row in accepted if row.get('result_lighthouse') is not None]
    summary['average_axe'] = sum(measured_axe) / len(measured_axe) if measured_axe else None
    summary['average_lighthouse'] = sum(measured_lighthouse) / len(measured_lighthouse) if measured_lighthouse else None
    summary['strategy_reducers'] = observed_reducer_rankings(accepted, strategies=True)
    summary['model_reducers'] = observed_reducer_rankings(accepted)
    summary['historical_import_cost'] = sum(float(row['total_cost_usd'] or 0) for row in histories if row.get('import_provenance_json'))
    summary['cost'] -= summary['historical_import_cost']
    from remediation_listing import hydrate_taxonomy
    hydrate_taxonomy(histories, get_connection)
    return render_template("remediation_history.html", runs=histories, summary=summary,
                           total_seconds=sum(float(row.get('execution_seconds') or 0) for row in histories),
                           has_active=bool(summary["active"]))


@remediation_bp.post('/<int:run_id>/stop')
def stop_run(run_id):
    from harness.routes import protect
    from harness.store import Store
    from harness.run_stop import requested, request_stop
    protect()
    connection = get_connection()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute('SELECT id,status FROM remediation_runs WHERE id=%s', (run_id,))
        run = cursor.fetchone()
        if not run:
            abort(404)
        if run['status'] not in {'queued', 'running'}:
            return jsonify(error=_('This execution has already finished.')), 409
        store = Store(current_app.config.get('HARNESS_ROOT'))
        if not requested(store, run_id):
            request_stop(store, run_id)
            cursor.execute('INSERT INTO remediation_events (run_id,actor,event_type,message,details_json,created_at) VALUES (%s,%s,%s,%s,%s,%s)',
                           (run_id, 'User', 'stop_requested', 'Stop requested by user', '{}', now_local()))
        if run['status'] == 'queued':
            cursor.execute("UPDATE remediation_runs SET status='stopped',current_phase='complete',progress_message=%s,completed_at=%s WHERE id=%s AND status='queued'",
                           ('Stopped by user before execution.', now_local(), run_id))
        connection.commit()
    finally:
        cursor.close()
        connection.close()
    if request.accept_mimetypes.best == 'application/json':
        return jsonify(stop_requested=True), 202
    return redirect(url_for('remediation.run_detail', run_id=run_id))


@remediation_bp.post("/<int:run_id>/delete")
def delete_run(run_id):
    conn=get_connection(); cursor=conn.cursor(dictionary=True)
    cursor.execute("SELECT id,status,published_experiment_id FROM remediation_runs WHERE id=%s",(run_id,)); run=cursor.fetchone()
    if not run:
        cursor.close(); conn.close(); flash(_("The requested remediation run does not exist."),"warning"); return redirect(url_for("remediation.runs"))
    if run["status"] in {"queued","running"}:
        cursor.close(); conn.close(); flash(_("A queued or running remediation cannot be deleted."),"warning"); return redirect(url_for("remediation.runs"))

    published_id=run.get("published_experiment_id")
    if published_id:
        cursor.execute("""SELECT COUNT(*) total FROM remediation_runs rr JOIN experiment_results er ON er.id=rr.source_result_id WHERE rr.id<>%s AND er.experiment_id=%s""",(run_id,published_id))
        if int((cursor.fetchone() or {}).get("total") or 0):
            cursor.close(); conn.close(); flash(_("This result is the source of another remediation run and cannot be deleted."),"warning"); return redirect(url_for("remediation.runs"))
    cursor.execute("SELECT output_path,screenshot_path FROM remediation_iterations WHERE run_id=%s",(run_id,)); artifacts=cursor.fetchall()
    try:
        cursor.execute("DELETE FROM remediation_runs WHERE id=%s",(run_id,))
        if published_id:
            cursor.execute("DELETE FROM experiment_results WHERE experiment_id=%s",(published_id,))
            cursor.execute("DELETE FROM experiment_environment WHERE experiment_id=%s",(published_id,))
            cursor.execute("DELETE FROM experiments WHERE id=%s",(published_id,))
        conn.commit()
    except Exception:
        conn.rollback(); cursor.close(); conn.close(); flash(_("The remediation run could not be deleted."),"danger"); return redirect(url_for("remediation.runs"))
    cursor.close(); conn.close()
    dataset_root=(DATASET_ROOT/"remediations").resolve(); run_directory=(dataset_root/str(run_id)).resolve()
    if dataset_root in run_directory.parents and run_directory.is_dir(): shutil.rmtree(run_directory,ignore_errors=True)
    results_root=Path("/results/raw").resolve()
    directories=set()
    for item in artifacts:
        screenshot=Path(item["screenshot_path"]).resolve() if item.get("screenshot_path") else None
        if screenshot and results_root in screenshot.parents and screenshot.parent.name.startswith(f"experiment_remediation_{run_id}_"): directories.add(screenshot.parent)
    if published_id: directories.add(results_root/f"experiment_{published_id}")
    for directory in directories:
        resolved=directory.resolve()
        if results_root in resolved.parents and resolved.is_dir(): shutil.rmtree(resolved,ignore_errors=True)
    flash(_("Remediation run and its generated evidence were deleted."),"success")
    return redirect(url_for("remediation.runs"))








@remediation_bp.route('/new', methods=['GET', 'POST'])
def new_run():
    if request.method == 'GET':
        return redirect(url_for('workspace.launch'))
    from remediation_submission import create_remediation
    from harness.routes import protect
    protect()
    try:
        ident = create_remediation(request.form, get_settings())
    except ValueError as error:
        flash(str(error), 'danger')
        return redirect(url_for('workspace.launch'))
    return redirect(url_for('remediation.run_detail', run_id=ident))


@remediation_bp.get('/<int:run_id>/live-events')
def live_events(run_id):
    from harness.store import Store
    from remediation_live_events import change_stream
    store=Store(current_app.config.get('HARNESS_ROOT'))
    def recorded_state():
        conn=get_connection();cursor=conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT status,current_phase,current_iteration,progress_percent,progress_message,total_cost_usd,harness_config_json FROM remediation_runs WHERE id=%s",(run_id,))
            state=cursor.fetchone()
            if not state:return None
            cursor.execute('SELECT MAX(id) latest,COUNT(*) count FROM remediation_events WHERE run_id=%s',(run_id,))
            state['events']=cursor.fetchone()
            cursor.execute('SELECT MAX(id) latest,COUNT(*) count FROM remediation_iterations WHERE run_id=%s',(run_id,))
            state['iterations']=cursor.fetchone()
        finally:cursor.close();conn.close()
        config=json.loads(state.pop('harness_config_json') or '{}')
        with store.connect()as db:
            if config.get('campaign_id'):
                state['receipts']=tuple(db.execute('SELECT MAX(created),COUNT(*) FROM records WHERE campaign=?',(config['campaign_id'],)).fetchone())
            row=db.execute('SELECT revision FROM checkpoints WHERE id=?',('sql-run-'+str(run_id)+'-taxonomy-progress',)).fetchone()
            state['taxonomy_revision']=row[0]if row else 0
            if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='calls'").fetchone():
                state['provider_calls']=[tuple(row) for row in db.execute('SELECT id,status,response_id FROM calls WHERE run=? ORDER BY created,id',('sql-run-'+str(run_id),))]
        return state
    if recorded_state()is None:return Response(status=404)
    return Response(stream_with_context(change_stream(recorded_state)),mimetype='text/event-stream',
        headers={'Cache-Control':'no-cache, no-store','X-Accel-Buffering':'no'})


@remediation_bp.get("/<int:run_id>")
def run_detail(run_id):
    conn=get_connection(); cursor=conn.cursor(dictionary=True)
    cursor.execute("""SELECT rr.*,COALESCE(r.display_name,r.page_title,r.url) source_name,r.url source_url,COALESCE(rr.baseline_axe,r.axe_wcag_violations) original_axe,r.axe_raw_path source_axe_raw_path,COALESCE(rr.baseline_lighthouse,r.lighthouse_score) original_lighthouse,r.wave_aim_score original_aim,t.name template_name FROM remediation_runs rr JOIN experiment_results r ON r.id=rr.source_result_id LEFT JOIN remediation_templates t ON t.id=rr.template_id WHERE rr.id=%s""",(run_id,)); run=cursor.fetchone()
    if not run: cursor.close(); conn.close(); return redirect(url_for("remediation.runs"))
    cursor.execute("SELECT * FROM remediation_iterations WHERE run_id=%s ORDER BY iteration_number",(run_id,)); iterations=[project_wcag(row) for row in cursor.fetchall()]
    cursor.execute("SELECT * FROM remediation_events WHERE run_id=%s ORDER BY id",(run_id,)); events=cursor.fetchall()
    model_roles={}; category_counts={"Syntactic":0,"Semantic":0,"Layout":0}; taxonomy=None
    from harness.store import Store
    import hashlib
    store = Store(current_app.config.get('HARNESS_ROOT'))
    try:
        config = json.loads(run.get('harness_config_json') or '{}')
    except (TypeError, ValueError):
        config = {}
    campaign = config.get('campaign_id')
    continuations = store.list('progress_continuation', campaign) if campaign else []
    continuation_by_iteration = {
        row['data']['reference_limits'].get('iteration'): row['data']
        for row in continuations if row['data'].get('run_id') == 'sql-run-' + str(run_id)
    }
    try:
        displayed_outcome = json.loads(run.get('harness_outcome_json') or '{}')
    except (TypeError, ValueError):
        displayed_outcome = {}
    run['visual_review_diagnostic'] = displayed_outcome.get('candidate_review_mode') == 'diagnostic-only'
    if displayed_outcome.get('resource_scope') == 'cleaned-experimental-execution':
        # Superseded continuation events are available in the cleanup archive.
        continuation_by_iteration = {}
    for item in iterations:
        for field,target in (("dom_changes_json","dom_changes"),("specialist_reviews_json","specialist_reviews"),("agent_usage_json","agent_usage"),("strategy_json","strategy")):
            fallback="{}" if target in {"dom_changes","strategy"} else "[]"
            try: item[target]=json.loads(item.get(field) or fallback)
            except (ValueError,TypeError): item[target]={} if target in {'dom_changes','strategy'} else []
        if run.get('execution_mode')=='single_shot' and item.get('strategy'):
            # Present old evidence with current process terminology; do not
            # rewrite stored prompts, model responses or scientific provenance.
            item['strategy'].setdefault('approach',{})['name']='Zero-shot — single call'
            item['strategy']['repair_engine']='Zero-shot prompting; one generation call; no planner, checker feedback, RAG, screenshot or repair postprocessor'
        iteration_presentation(item, run_id, DATASET_ROOT)
        item['continuation_review'] = continuation_by_iteration.get(item['iteration_number'])
        target_presentation(run,item)
        recorded_roles=[(entry.get('role') or 'Agent',entry.get('model')) for entry in item['agent_usage'] if isinstance(entry,dict)]
        if not recorded_roles:
            recorded_roles=[('Generator',item.get('generator_model'))]
            if run.get('review_policy') != 'automated':
                recorded_roles.append(('Coordinator',item.get('reviewer_model')))
        for role,model in recorded_roles:
            if model and not model.startswith("system/"): model_roles.setdefault(model,set()).add(role)
        for review in item["specialist_reviews"]:
            if review.get("model"): model_roles.setdefault(review["model"],set()).add(review.get("role") or "Specialist")
            if review.get("status") in {"advisory","blocker"} and review.get("category") in category_counts:
                category_counts[review["category"]]+=max(1,len(review.get("findings") or []))
        if item.get("strategy",{}).get("taxonomy"):
            taxonomy=dict(item["strategy"]["taxonomy"])
            # Recompute display-only categories from saved evidence; the stored
            # strategy, reviewer decisions and event log remain immutable.
            if Path(run.get('source_axe_raw_path') or '').is_file() and Path(item.get('axe_raw_path') or '').is_file():
                taxonomy['original']=axe_taxonomy(run['source_axe_raw_path'])
                taxonomy['candidate']=axe_taxonomy(item['axe_raw_path'])
    participants=[{"model":model,"roles":", ".join(sorted(roles))} for model,roles in model_roles.items()]
    from harness.store import Store
    events=decision_activity_events(run,events,Store(current_app.config.get('HARNESS_ROOT')),get_settings()['app_timezone'],str(get_locale()))
    for event in events:
        event_presentation(event)
        event['activity_message']=progress_presentation(event['activity_message'],_)
    run['display_progress_message']=progress_presentation(run.get('progress_message'),_)
    run['live_participants']=live_loop_participants(events)
    run['live_provider_activity']=live_provider_activity(Store(current_app.config.get('HARNESS_ROOT')),run_id)
    run['live_taxonomy_progress']=Store(current_app.config.get('HARNESS_ROOT')).checkpoint('sql-run-'+str(run_id)+'-taxonomy-progress')[0]
    rejected_best=best_measured(run,iterations)
    best=retained_summary(run,iterations)
    run['execution_counts'] = execution_counts(run, iterations)
    from harness.run_stop import requested
    run['stop_requested'] = requested(store, run_id)
    ordinals = iteration_ordinals(iterations)
    for item in iterations:
        item['display_iteration_number'] = ordinals[item['id']]
    if best and best.get('id') in ordinals:
        best['display_iteration_number'] = ordinals[best['id']]
    if rejected_best and best and rejected_best.get('id')==best.get('id'):rejected_best=None
    try: run['harness_outcome']=json.loads(run.get('harness_outcome_json') or 'null')
    except (ValueError,TypeError):run['harness_outcome']=None
    from remediation_stop_presentation import stop_notice
    stop_manifest = None
    stop_reason = run.get('error_message') or (run['harness_outcome'] or {}).get('stop_reason') or ''
    if campaign and 'per-call cost limit' in stop_reason.lower():
        try:
            stop_manifest = store.get(campaign)['data']
        except KeyError:
            pass
    run['stop_notice'] = stop_notice(run, _, stop_manifest)
    from remediation_continuation_presentation import continuation_note
    for index, item in enumerate(iterations):
        item['continuation_note'] = continuation_note(item, run, index < len(iterations) - 1, _)
    if best:run['recorded_output_format']=best.get('recorded_output_format')
    run['display_progress_message']=retained_progress(run,best.get('display_iteration_number') if best else None,
        best.get('axe_violations') if best else None,best.get('lighthouse_score') if best else None,_)
    run["improvement"]=improvement_metrics(run.get("original_axe"),best.get("axe_violations") if best else None,run.get("original_lighthouse"),best.get("lighthouse_score") if best else None)
    run['presentation_priority']=presentation_priority(run.get('accessibility_priority'),best.get('strategy',{}) if best else None)
    initial_strategy=iterations[0].get('strategy',{}) if iterations else {}
    run['presentation_name']=presentation_name(run.get('accessibility_priority'),initial_strategy)
    from harness.store import Store
    run['dynamic_level']=dynamic_presentation(run,Store(current_app.config.get('HARNESS_ROOT')))
    if run['dynamic_level']:
        run['presentation_name']='Dynamic harness'
        run['presentation_priority']=105
    from remediation_interventions import presentation
    run.update(presentation(run,initial_strategy))
    from remediation_route_presentation import execution_route
    route_decisions = store.list('decision', campaign) if run['dynamic_level'] and campaign else []
    run['execution_route'] = execution_route(run, iterations, route_decisions)
    run['model_presentation']=run_model_presentation(run)
    from accessibility_taxonomy.presentation import details as taxonomy_details
    run['taxonomy_details']=taxonomy_details((run.get('harness_outcome') or {}).get('taxonomy_measurement'),Store(current_app.config.get('HARNESS_ROOT')))
    report_candidate_available=bool(best and best.get('output_path') and Path(best['output_path']).is_file())
    response = Response(render_template("remediation_detail.html",run=run,iterations=iterations,participants=participants,events=events,category_counts=category_counts,taxonomy=taxonomy,best_candidate=best,rejected_best=rejected_best,report_candidate_available=report_candidate_available,partial_report=request.args.get('live') == '1'), mimetype='text/html')
    response.headers['Cache-Control'] = 'no-store'
    return response







@remediation_bp.get("/<int:run_id>/iterations/<int:iteration_id>/candidate")
def candidate_file(run_id, iteration_id):
    conn=get_connection(); cursor=conn.cursor(dictionary=True)
    cursor.execute("SELECT output_path FROM remediation_iterations WHERE id=%s AND run_id=%s",(iteration_id,run_id)); item=cursor.fetchone(); cursor.close(); conn.close()
    path=Path(item["output_path"]).resolve() if item and item.get("output_path") else None
    allowed=(DATASET_ROOT/"remediations").resolve()
    if not path or allowed not in path.parents or not path.is_file(): return Response(status=404)
    return send_file(path,mimetype="text/html",conditional=True)


@remediation_bp.get('/<int:run_id>/iterations/<int:iteration_id>/page')
def candidate_page(run_id, iteration_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('SELECT output_path FROM remediation_iterations WHERE run_id=%s AND id=%s',
                       (run_id, iteration_id))
        item = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
    directory = (DATASET_ROOT / 'remediations' / str(run_id)).resolve()
    path = Path(item['output_path']).resolve() if item and item.get('output_path') else None
    if not path or directory not in path.parents or not path.is_file():
        return Response(status=404)
    return redirect(url_for('remediation.dataset_page', run_id=run_id,
                            filename=path.relative_to(directory).as_posix()))


from dataset_navigation import isolated_page, serve_dataset_file


@remediation_bp.get('/<int:run_id>/original/page')
def original_page(run_id):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute('''SELECT r.response_source_path,r.source_snapshot_path,d.storage_key,o.relative_path
                          FROM remediation_runs rr
                          JOIN experiment_results r ON r.id=rr.source_result_id
                          LEFT JOIN dataset_observations o ON o.id=r.dataset_observation_id
                          LEFT JOIN datasets d ON d.id=o.dataset_id WHERE rr.id=%s''', (run_id,))
        source = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()
    if not source:
        return Response(status=404)
    baseline = DATASET_ROOT / 'remediations' / str(run_id) / 'source-baseline.html'
    if baseline.is_file():
        return redirect(url_for('remediation.dataset_page', run_id=run_id,
                                filename='source-baseline.html'))
    stored_path = source_snapshot(source)
    if not stored_path:
        return Response(status=404)
    return isolated_page(send_file(stored_path, mimetype='text/html', conditional=True))


@remediation_bp.get('/<int:run_id>/dataset/<path:filename>')
def dataset_page(run_id, filename):
    """Navigate stored pages through the UI, keeping dataset-server internal."""
    from remediation_saved_page import measured_page
    from harness.contracts import ContractError
    try:
        measured = measured_page(run_id, filename, DATASET_ROOT)
    except ContractError:
        return Response(status=409)
    if measured is not None:
        return measured
    directory = DATASET_ROOT / 'remediations' / str(run_id)
    return serve_dataset_file(directory, filename, DATASET_ROOT)


@remediation_bp.get('/<int:run_id>/saved/<token>/<path:filename>')
def saved_candidate_file(run_id, token, filename):
    from remediation_saved_page import saved_file
    return saved_file(run_id, token, filename, DATASET_ROOT)


@remediation_bp.get("/<int:run_id>/iterations/<int:iteration_id>/screenshot")
def candidate_screenshot(run_id, iteration_id):
    from remediation_capture_preview import refreshed_capture

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT screenshot_path,output_path FROM remediation_iterations WHERE id=%s AND run_id=%s",
        (iteration_id, run_id))
    item = cursor.fetchone()
    cursor.close()
    conn.close()
    path = Path(item['screenshot_path']).resolve() if item and item.get('screenshot_path') else None
    allowed = Path('/results/raw').resolve()
    if not path or allowed not in path.parents or not path.is_file():
        return Response(status=404)
    preview = refreshed_capture(
        DATASET_ROOT / 'remediations' / str(run_id), iteration_id,
        item.get('output_path'), path, allowed)
    response = send_file(preview or path, mimetype='image/jpeg', conditional=True)
    if preview:
        response.headers['Cache-Control'] = 'no-store'
    return response


@remediation_bp.get("/<int:run_id>/original/screenshot")
def original_screenshot(run_id):
    conn=get_connection(); cursor=conn.cursor(dictionary=True)
    cursor.execute("SELECT r.screenshot_path FROM remediation_runs rr JOIN experiment_results r ON r.id=rr.source_result_id WHERE rr.id=%s",(run_id,)); item=cursor.fetchone(); cursor.close(); conn.close()
    path=Path(item["screenshot_path"]).resolve() if item and item.get("screenshot_path") else None
    allowed=Path("/results/raw").resolve()
    if not path or allowed not in path.parents or not path.is_file(): return Response(status=404)
    return send_file(path,mimetype="image/jpeg",conditional=True)


@remediation_bp.get('/<int:run_id>/iterations/<int:iteration_id>/open')
def open_candidate(run_id, iteration_id):
    return redirect(url_for('remediation.candidate_page', run_id=run_id, iteration_id=iteration_id))
