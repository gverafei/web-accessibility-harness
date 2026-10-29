"""Create a bounded remediation from an existing immutable acquisition."""
import os
import json
from flask import current_app
from flask_babel import gettext as _
from database import get_connection
from remediation_recipes import automatic_recipe, common_conditions
from remediation_model_choices import model_choice, frozen_model_configuration
from routes.remediation import source_snapshot, classified_page_type, now_local

def create_remediation(form, settings, *, frozen_source_binding=None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        result_id = form.get('source_result_id', type=int)
        template_id = None
        cursor.execute("SELECT r.*,d.storage_key,o.relative_path FROM experiment_results r LEFT JOIN dataset_observations o ON o.id=r.dataset_observation_id LEFT JOIN datasets d ON d.id=o.dataset_id WHERE r.id=%s AND r.status='completed'", (result_id,))
        source = cursor.fetchone()
        if not source or not source_snapshot(source):
            raise ValueError(_('This legacy acquisition has no stored HTML snapshot and cannot be remediated reproducibly.'))
        from remediation_interventions import VERSION as CURRENT_INTERVENTIONS, LEGACY_VERSION, validate_version
        intervention_version = form.get('intervention_version', CURRENT_INTERVENTIONS)
        if intervention_version != CURRENT_INTERVENTIONS:
            raise ValueError(_('Choose a current intervention policy.'))
        current_interventions = intervention_version == CURRENT_INTERVENTIONS
        preservation_levels = {0: 15, 1: 55, 2: 75, 3: 90, 4: 15} if current_interventions else {0: 15, 1: 35, 2: 55, 3: 75, 4: 90}
        requested_level = form.get('preservation_level', type=int)
        priority = preservation_levels.get(requested_level, max(0, min(100, form.get('accessibility_priority', type=int) or 15)))
        if requested_level is None:
            requested_level = {15: 0, 55: 1, 75: 2, 90: 3}.get(priority)
        if requested_level not in preservation_levels or priority not in {15, 55, 75, 90}:
            raise ValueError(_('Choose a current intervention policy.'))
        expert = form.get('use_expert_settings') == 'on'
        execution_mode = form.get('execution_mode', 'iterative')
        if execution_mode not in {'iterative', 'single_shot', 'regenerate_only', 'regenerate_refine'}:
            execution_mode = 'iterative'
        if priority >= 75 and execution_mode == 'iterative':
            execution_mode = 'regenerate_refine'
        selection = 'component_knowledge'
        rationale = 'No prescribed template; native component guidance follows observed evidence.'
        requested_format = form.get('transformation_format', 'html') if expert else 'auto'
        if requested_format not in {'auto', 'html', 'markdown'}:
            requested_format = 'auto'
        page_type = classified_page_type(source_snapshot(source))
        representation = ('markdown' if priority >= 80 else 'html') if requested_format == 'auto' else requested_format
        if current_interventions:
            representation = 'markdown' if priority == 90 else 'html'
        recipe = automatic_recipe(priority, execution_mode, settings=settings)
        requested_temperature = form.get('temperature', type=float)
        if form.get('temperature_configured') == '1' and (requested_temperature is None or not __import__('math').isfinite(requested_temperature) or (not 0 <= requested_temperature <= 1)):
            raise ValueError(_('Invalid temperature. Use a number from 0 to 1.'))
        temperature = max(0, min(1, requested_temperature if requested_temperature is not None else recipe['temperature'])) if expert or form.get('temperature_configured') == '1' else recipe['temperature']
        selected_model = form.get('selected_model', '')
        try:
            choice = model_choice(selected_model, settings)
        except ValueError:
            raise ValueError(_('Choose a model from the configured slider.'))
        mode = 'user'
        tier = choice['tier']
        generator_model = reviewer_model = choice['model']
        provider = reviewer = generator_model.split('/', 1)[0]
        run_limits = common_conditions(settings)
        if requested_level == (4 if current_interventions else 5) and (not expert) and (form.get('run_limits_configured') != '1'):
            run_limits.update(iterations=5, seconds=900)
        if expert or form.get('run_limits_configured') == '1':
            try:
                run_limits = common_conditions({'remediation_' + key: form.get(key, settings['remediation_' + key]) for key in ('max_iterations', 'min_lighthouse', 'max_axe', 'max_cost_usd', 'max_execution_seconds')})
            except ValueError:
                raise ValueError(_('Invalid remediation settings. Check the target and resource-limit ranges.'))
        maximum = run_limits['iterations']
        if current_interventions and (not (expert or form.get('temperature_configured') == '1')):
            temperature = 0.05
        review_policy = 'automated'
        title = (form.get('title') or f"Remediation of {source.get('display_name') or source['url']}")[:180]
        use_wave = False
        act_default = 'off' if form.get('act_grounding_configured') == '1' else 'on'
        use_rag = form.get('act_grounding', act_default) != 'off'
        if execution_mode == 'single_shot':
            maximum = 1
            review_policy = 'automated'
            use_rag = False
            representation = 'html'
        if execution_mode in {'regenerate_only', 'regenerate_refine'}:
            if not (expert or form.get('temperature_configured') == '1') or requested_temperature is None:
                temperature = 0.05 if current_interventions else 0.5
            review_policy = 'automated'
            if execution_mode == 'regenerate_only':
                maximum = 1
            selection = 'source_reference'
            rationale = 'Acquired source evidence; free composition without a prescribed template.'
        rag_top_k = max(2, min(12, form.get('rag_top_k', type=int) or recipe['rag_top_k'])) if expert or form.get('run_limits_configured') == '1' else recipe['rag_top_k']
        max_cost = run_limits['cost']
        max_seconds = run_limits['seconds']
        min_lighthouse = run_limits['lighthouse']
        max_axe = run_limits['axe']
        min_aim = None
        harness_config = None
        if form.get('harness_enabled') == '1' or not os.getenv('HARNESS_TESTING'):
            try:
                from harness.remediation_bridge import configure
                from harness.store import Store
                values = dict(form, intervention_version=intervention_version, preservation_level=str(requested_level))
                values.update(title=title, max_iterations=str(maximum), max_cost_usd=str(max_cost), max_execution_seconds=str(max_seconds), max_axe=str(max_axe), min_lighthouse=str(min_lighthouse), rag_top_k=str(rag_top_k))
                binding = ({'frozen_source_binding': frozen_source_binding}
                           if frozen_source_binding is not None else {})
                harness_config = configure(Store(current_app.config.get('HARNESS_ROOT')), settings, source, choice, values, **binding)
            except (ValueError, KeyError) as error:
                raise ValueError(_(str(error)))
        cursor.execute("INSERT INTO remediation_runs (source_result_id,template_id,title,transformation_format,generator_provider,generator_model,reviewer_provider,reviewer_model,max_iterations,min_lighthouse,max_axe,min_aim,status,created_at,accessibility_priority,temperature,template_selection,template_rationale,use_wave,model_selection_mode,model_cost_tier,allowed_models_json,max_dom_distance,enforce_dom_distance,review_policy,max_cost_usd,max_execution_seconds,use_rag,rag_top_k) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (result_id, template_id, title, representation, provider, generator_model, reviewer, reviewer_model, maximum, min_lighthouse, max_axe, min_aim if use_wave else None, now_local(), priority, temperature, selection, rationale, use_wave, mode, tier, json.dumps([generator_model]), priority, False, review_policy, max_cost, max_seconds, use_rag, rag_top_k))
        run_id = cursor.lastrowid
        cursor.execute('UPDATE remediation_runs SET intervention_version=%s WHERE id=%s', (intervention_version, run_id))
        if harness_config:
            cursor.execute('UPDATE remediation_runs SET harness_config_json=%s WHERE id=%s', (json.dumps(harness_config), run_id))
        cursor.execute('UPDATE remediation_runs SET model_config_json=%s WHERE id=%s', (json.dumps(dict(frozen_model_configuration(choice), submission_id=form.get('submission_id'))), run_id))
        cursor.execute('UPDATE remediation_runs SET use_expert_settings=%s WHERE id=%s', (expert, run_id))
        if generator_model.startswith('ollama/'):
            from local_llm import local_configuration
            cursor.execute('UPDATE remediation_runs SET local_llm_config_json=%s WHERE id=%s', (json.dumps(local_configuration(settings)), run_id))
        cursor.execute('UPDATE remediation_runs SET execution_mode=%s WHERE id=%s', (execution_mode, run_id))
        evidence_mode = form.get('generator_evidence_mode', 'guided') if expert else 'guided'
        if evidence_mode not in {'guided', 'localized', 'independent'}:
            evidence_mode = 'guided'
        cursor.execute('UPDATE remediation_runs SET generator_evidence_mode=%s WHERE id=%s', (evidence_mode, run_id))
        reconstruction_mode = form.get('reconstruction_mode', 'whole_page') if expert else 'whole_page'
        if reconstruction_mode not in {'whole_page', 'fragmented'}:
            reconstruction_mode = 'whole_page'
        cursor.execute('UPDATE remediation_runs SET reconstruction_mode=%s WHERE id=%s', (reconstruction_mode, run_id))
        markdown_provider = form.get('markdown_provider', 'local') if expert else 'local'
        if markdown_provider not in {'local', 'jina'}:
            markdown_provider = 'local'
        cursor.execute('UPDATE remediation_runs SET markdown_provider=%s WHERE id=%s', (markdown_provider, run_id))
        conn.commit()
        return run_id
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
