"""Models and read-only harness component catalogues."""
import json

import requests

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _

from harness.component_inventory import AGENTS
from harness.routes import csrf, protect, store
from remediation_tools import TOOL_CONTRACTS
from settings import get_settings, save_settings

components_bp = Blueprint('components', __name__)


@components_bp.get('/models')
def models():
    from remediation_model_choices import configured_catalog
    from harness.decision_models import catalogue
    settings = get_settings()
    csrf()
    tab = request.args.get('tab', 'generative')
    if tab not in ('generative', 'decisions', 'local'):
        abort(400)
    return render_template('harness/models.html', tab=tab,
        catalog=configured_catalog(settings), decision_catalog=catalogue(settings),
        decision_editor=tab == 'decisions', settings={key: settings.get(key, '')
        for key in ('ollama_base_url', 'ollama_model')})


@components_bp.post('/models/local')
def local_models():
    protect()
    from local_llm import installed_local_models, local_configuration
    values = {key: request.form.get(key, '').strip()
              for key in ('ollama_base_url', 'ollama_model')}
    try:
        config = local_configuration(values)
        capabilities = []
        if config:
            choice = next((item for item in installed_local_models(config['base_url'])
                           if item['id'] == config['model']), None)
            if not choice or choice.get('capabilities_verified') is False:
                raise ValueError('Select an installed local model.')
            capabilities = choice['capabilities']
        values['ollama_capabilities_json'] = json.dumps(capabilities)
        save_settings(values)
        flash(_('Local model settings saved.'), 'success')
    except (ValueError, requests.RequestException):
        flash(_('Could not save Ollama. Select an installed model from a reachable server, or clear both fields to disable it.'), 'danger')
    return redirect(url_for('components.models', tab='local'))


@components_bp.get('/skills')
def skills():
    from remediation_skill_catalog import MANIFEST, SkillCatalog
    from remediation_interventions import VERSION, skill_manifest
    path = MANIFEST.with_name(skill_manifest(VERSION))
    catalog = SkillCatalog(path)
    return render_template('harness/skills.html', skills=list(catalog.skills.values()),
                           source_path='web/app/agent_skills/' + path.name)


@components_bp.get('/tools')
def tools():
    return render_template('harness/tools.html', tools=list(TOOL_CONTRACTS.values()))


@components_bp.get('/agents')
def agents():
    return render_template('harness/agents.html', agents=AGENTS)
