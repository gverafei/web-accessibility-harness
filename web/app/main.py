import os

from flask import Flask, current_app, render_template, session
from flask_babel import Babel
from config import Config, ResearchRequest
from database import init_db
from settings import get_settings
from harness.routes import bp, csrf
from routes.model_catalog import model_catalog_bp
from routes.experiments import experiments_bp
from routes.remediation import remediation_bp
from routes.rag_maintenance import rag_maintenance_bp
from routes.taxonomy import taxonomy_bp
from routes.components import components_bp
from routes.workspace import workspace_bp
from routes.papers import papers_bp
from download_feedback import signal_download_ready

def select_locale():
    value=session.get('language', current_app.config['BABEL_DEFAULT_LOCALE'])
    return value if value in current_app.config['BABEL_SUPPORTED_LOCALES'] else 'en'

def create_app(test_config=None):
    app=Flask(__name__);app.config.from_object(Config)
    app.config['READ_ONLY'] = os.getenv('HARNESS_READ_ONLY') == '1'

    if os.getenv('HARNESS_TESTING')=='1':app.config['TESTING']=True
    if test_config: app.config.update(test_config)
    if app.config.get('TESTING') and 'BABEL_DEFAULT_LOCALE' not in (test_config or {}):
        app.config['BABEL_DEFAULT_LOCALE'] = 'en'
    # Cookies share a host across ports; isolate the preview session.
    default_cookie = app.config['SESSION_COOKIE_NAME']
    app.config['SESSION_COOKIE_NAME'] = (os.getenv('SESSION_COOKIE_NAME')
        or (test_config or {}).get('SESSION_COOKIE_NAME', default_cookie))
    if not app.config.get('TESTING') and not app.config['READ_ONLY'] and not os.getenv('SECRET_KEY'):
        from pathlib import Path
        import secrets
        root=Path(os.getenv('HARNESS_ROOT','/data/harness'));root.mkdir(parents=True,exist_ok=True)
        secret=root/'.session-key'
        try:
            fd=os.open(secret,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as stream: stream.write(secrets.token_hex(32))
        except FileExistsError: pass
        app.config['SECRET_KEY']=secret.read_text()
    if app.config['READ_ONLY']:
        app.config['SECRET_KEY'] = __import__('secrets').token_hex(32)
        @app.before_request
        def read_only_request():
            from flask import request, abort
            if (request.method not in ('GET', 'HEAD', 'OPTIONS')
                    and request.endpoint != 'experiments.set_theme'):
                abort(403, description='This preview is read-only.')
    app.request_class=ResearchRequest
    Babel(app,locale_selector=select_locale)
    from summary_metrics import score_number, elapsed_time
    app.jinja_env.filters['score_number'] = score_number
    app.jinja_env.filters['elapsed_time'] = elapsed_time
    from accessibility_taxonomy.presentation import counts
    app.jinja_env.filters['taxonomy_counts']=counts
    from accessibility_taxonomy.presentation import details
    app.jinja_env.filters['taxonomy_details']=details
    @app.context_processor
    def shared_context():
        from navigation import NAVIGATION
        return {'current_locale':select_locale(),'ui_theme':session.get('ui_theme','light'), 'workspace_navigation':NAVIGATION}
    if (not app.config.get('TESTING') and not app.config['READ_ONLY']
            and os.getenv('HARNESS_INIT_DB', '1') != '0'):
        with app.app_context(): init_db()
    app.after_request(signal_download_ready)
    app.register_blueprint(workspace_bp)
    app.register_blueprint(experiments_bp)
    app.register_blueprint(remediation_bp)
    app.register_blueprint(rag_maintenance_bp)
    app.register_blueprint(taxonomy_bp)
    app.register_blueprint(bp,url_prefix='/harness')
    app.register_blueprint(model_catalog_bp)
    app.register_blueprint(components_bp)
    app.register_blueprint(papers_bp)
    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error('Unexpected application error',exc_info=error.original_exception or error)
        return render_template('error.html'),500
    return app

# Tests import create_app without connecting to any running database.
app=create_app({'TESTING':True}) if os.getenv('HARNESS_TESTING')=='1' else create_app()
if __name__=='__main__': app.run(host='0.0.0.0',port=5000)
