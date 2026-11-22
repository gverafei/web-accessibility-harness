"""Logical navigation for the task-focused harness interface."""
from flask import request, url_for
from flask_babel import gettext as _

NAVIGATION = (
    ('workspace.launch','Start'), ('experiments.index','Activity'),
    ('experiments.experiments','Captures'), ('remediation.runs','Executions'),
    ('rag_maintenance.examples','RAG-ACT'), ('taxonomy.index','Taxonomy'),
    ('components.models','Models'), ('components.skills','Skills'),
    ('components.tools','Tools'), ('components.agents','Agents'),
    ('harness.configuration','Configuration'),
)


def breadcrumbs():
    endpoint = request.endpoint
    for name,label in NAVIGATION:
        if endpoint==name:
            return [{'label':_(label)}]
    if endpoint == 'workspace.preparing':
        return [{'label': _('Executions'), 'url': url_for('remediation.runs')},
                {'label': _('Remediation in progress')}]
    if endpoint=='remediation.run_detail':
        return [{'label':_('Executions'),'url':url_for('remediation.runs')},
                {'label':_('Execution #%(id)s',id=request.view_args['run_id'])}]
    if endpoint in ('experiments.experiment_report','experiments.experiment_report_loading'):
        return [{'label':_('Captures'),'url':url_for('experiments.experiments')},
                {'label':_('Capture #%(id)s',id=request.view_args['experiment_id'])}]
    return [{'label':_('Page')}]
