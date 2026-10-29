"""Read-only runtime/source fingerprint; campaign execution cannot silently change code."""
import hashlib
import importlib.metadata
import platform
from pathlib import Path
from .contracts import digest


def snapshot():
    app=Path(__file__).resolve().parents[1]
    # Fingerprint the restored runtime too: planners, jobs and source helpers
    # influence outputs just as the additive harness controller does.
    files={str(p.relative_to(app)):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in app.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.md','.js')
           and '__pycache__' not in p.parts}
    packages={name:importlib.metadata.version(name) for name in ('Flask','requests','beautifulsoup4')}
    return {'source_files':files,'code_digest':digest(files),'packages':packages,'python':platform.python_version()}
