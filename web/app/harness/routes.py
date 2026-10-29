"""Harness configuration and request contracts."""
import json
import secrets
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_babel import gettext as _
from .contracts import CRITERIA, STATES
from .store import Store
from . import decision_models
from .ui import display_label, policy_label, agreement_label
from settings import get_settings, save_settings, SECRET_SETTINGS
from remediation_model_choices import configured_catalog

bp = Blueprint('harness', __name__)

def store(): return Store(current_app.config.get('HARNESS_ROOT'))


def csrf():
    if 'csrf_token' not in session: session['csrf_token']=secrets.token_urlsafe(32)
    return session['csrf_token']


@bp.before_request
def protect():
    if request.method=='POST' and not secrets.compare_digest(str(request.form.get('csrf_token') or request.headers.get('X-CSRF-Token') or ''),csrf()):
        abort(400,description='Reload the form before submitting')


@bp.app_context_processor
def context():
    from navigation import breadcrumbs as original_breadcrumbs
    trail = original_breadcrumbs()
    return {'csrf_token':csrf,'criteria':CRITERIA,'review_states':STATES,'display_label':display_label,'policy_label':policy_label,'breadcrumbs':trail,'translate_label':_,'agreement_label':agreement_label}


@bp.route('/configuration',methods=['GET','POST'])
def configuration():
    if request.method=='GET':
        csrf()
        from routes.experiments import configuration as general_configuration
        return general_configuration()
    if request.method=='POST':
        if request.form.get('action')=='decisions':
            enabled=request.form.getlist('enabled_decisions');default=request.form.get('default_decision')
            choices=decision_models.validate_catalogue([dict(v,enabled=v['id'] in enabled,is_default=v['id']==default) for v in decision_models.catalogue(get_settings())])
            save_settings({decision_models.CATALOG_SETTING:json.dumps(choices)});flash(_('Decision models saved.'),'success')
            return redirect(url_for('harness.configuration',tab='decisions'))
        values={key:request.form[key] for key in ('openrouter_api_key','openrouter_base_url') if request.form.get(key,'').strip()}
        save_settings(values);flash(_('Server settings saved.'),'success')
        return redirect(url_for('harness.configuration'))
    settings=get_settings()
    return render_template('harness/configuration.html',settings={k:v for k,v in settings.items() if k not in SECRET_SETTINGS},
      configured={key:bool(settings.get(key)) for key in SECRET_SETTINGS},catalog=configured_catalog(settings),decision_catalog=decision_models.catalogue(settings),tab=request.args.get('tab','generative'))


@bp.get('/language/<language>')
def set_language(language):
    if language not in ('en','es'): abort(400)
    session['language']=language
    next_url=request.args.get('next','/')
    return redirect(next_url if next_url.startswith('/') and not next_url.startswith('//') else '/')


@bp.get('/theme/<theme>')
def set_theme(theme):
    if theme not in ('light','dark','system'): abort(400)
    session['ui_theme']=theme
    return jsonify(theme=theme) if request.accept_mimetypes.best=='application/json' else redirect(request.referrer or '/')
