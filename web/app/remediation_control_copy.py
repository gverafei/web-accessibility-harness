"""User-facing intervention descriptions shared by web and extension controls."""
from remediation_approaches import APPROACHES
from remediation_interventions import POLICIES, VERSION, LEGACY_VERSION, validate_version

PRESENTATION = (
    ('Maximum visual preservation', 'Smallest repairs; preserves native layout and behavior.'),
    ('Preservation first', 'Limited semantic and contrast correction.'),
    ('Accessibility with controlled change', 'Recognizable design with targeted repair.'),
    ('Accessibility first', 'Regenerate from complete HTML, then refine with localized patches.'),
    ('Screen-reader first', 'Regenerate from Markdown with greater design freedom, then refine with localized patches.'),
)


def control_copy(translate=lambda value: value, version=VERSION):
    validate_version(version)
    current=version==VERSION
    policies=[p.approach()for p in POLICIES]if current else APPROACHES
    presentation=(
        ('Structure and tasks preserved','Attributes, small adjunct labels and targeted CSS; no replacement or restructuring.'),
        ('Structure and tasks preserved','Component semantic repair and verified root-cause dependencies; no page redesign.'),
        ('New design from HTML','Complete HTML, purpose and reference capture guide a freely composed accessible page.'),
        ('New design from Markdown','Verified Markdown, purpose and reference capture guide a freely composed accessible page.'),
    )if current else PRESENTATION
    return {
        'intervention_version':version,
        'tiers': {key: translate(value) for key, value in (
            ('local', 'Local'), ('low', 'Light'), ('medium', 'Medium'),
            ('high', 'High'), ('xhigh', 'Extra high'), ('max', 'Ultra'))},
        'preservation': [
            {'name': translate(approach.name), 'subtitle': translate(subtitle),
             'description': translate(description)}
            for approach, (subtitle, description) in zip(policies, presentation)
        ],
        'labels': {key: translate(value) for key, value in (
            ('temperature', 'Temperature'), ('iterations', 'iterations'),
            ('act', 'RAG-ACT examples'), ('native', 'Native / scoped components'))},
    }
