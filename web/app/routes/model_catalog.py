"""Explicit catalogue administration; no model generation or implicit refresh."""
import json
import requests
from flask_babel import gettext as _
from flask import Blueprint, jsonify, request
from remediation_model_choices import CATALOG_SETTING, configured_catalog, discover_models, validate_catalog
from settings import get_settings, save_settings
from harness import decision_models
from model_catalog_metadata import cache_key, reviewed_metadata

model_catalog_bp = Blueprint('model_catalog', __name__, url_prefix='/configuration/models')


@model_catalog_bp.get('/discover')
def discover():
    try:
        models=discover_models(get_settings())
        save_settings({cache_key('generative'):json.dumps({m['model']:m for m in models},ensure_ascii=False)})
        return jsonify(models=models)
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return jsonify(error=_('Could not load the provider catalogue.')), 502


@model_catalog_bp.get('')
def get_catalog():
    return jsonify(choices=configured_catalog(get_settings()))


@model_catalog_bp.post('')
def save_catalog():
    from harness.routes import protect
    protect()
    payload = request.get_json(silent=True) or {}
    try:
        choices = validate_catalog(payload.get('choices'),reviewed_metadata(get_settings()))
        from harness.worker_profile import validate
        validate([c for c in choices if c['enabled']])
    except (ValueError, TypeError) as error:
        return jsonify(error=_(str(error))), 400
    save_settings({CATALOG_SETTING: json.dumps(choices, ensure_ascii=False)})
    return jsonify(choices=choices, message=_('Model catalogue saved.'))

@model_catalog_bp.get('/decisions')
def get_decision_catalog():
    return jsonify(choices=decision_models.catalogue(get_settings()))

@model_catalog_bp.get('/decisions/discover')
def discover_decisions():
    try:
        models=decision_models.discover_models(get_settings())
        save_settings({cache_key('decisions'):json.dumps({m['model']:m for m in models},ensure_ascii=False)})
        return jsonify(models=models)
    except (requests.RequestException,ValueError,TypeError,KeyError):
        return jsonify(error=_('Could not load the provider catalogue.')),502

@model_catalog_bp.post('/decisions')
def save_decision_catalog():
    from harness.routes import protect
    protect()
    try:
        choices=decision_models.validate_catalogue((request.get_json(silent=True) or {}).get('choices'),reviewed_metadata(get_settings(),'decisions'))
        if any(c['enabled'] and c['model']!='openai/gpt-6-luna-decisions' for c in choices):
            raise ValueError('Closed tasks use Decisions Luna.')
    except (ValueError,TypeError) as error:
        return jsonify(error=_(str(error))),400
    save_settings({decision_models.CATALOG_SETTING:json.dumps(choices,ensure_ascii=False)})
    return jsonify(choices=choices,message=_('Decision models saved.'))
