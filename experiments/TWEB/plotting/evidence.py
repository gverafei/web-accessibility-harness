"""Bind plotted values to local evidence and record reproducible figure outputs."""
import csv
import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path

CACHE = tempfile.TemporaryDirectory(prefix='harness-plot-cache-')
os.environ.setdefault('MPLCONFIGDIR', CACHE.name)


def read_csv(package, name):
    with (package / 'data' / name).open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind_inputs(package, names):
    """Validate the immutable export's checksum before using any measurement."""
    expected = json.loads((package / 'data/checksums.json').read_text())['files']
    bindings = {}
    for name in names:
        relative = 'data/' + name
        actual = sha256(package / relative)
        if expected.get(relative) != actual:
            raise ValueError('Evidence checksum mismatch: ' + relative)
        bindings[relative] = actual
    return bindings


def save_manifest(package, output, inputs, figures, statistics):
    """Record figure pixels, input bindings, code versions and plotted summaries."""
    import matplotlib
    import numpy
    import PIL
    from .check_figure_resolution import check_figure

    for relative, expected in inputs.items():
        if sha256(package / relative) != expected:
            raise ValueError('Input changed while plotting: ' + relative)
    images = []
    for name, (number, label) in figures.items():
        source = output / (name + '.png')
        target = output / f'figure-{number:02d}-{name}.png'
        source.replace(target)
        image = check_figure(target, check_only=True)
        image.pop('file')
        images.append({'file': target.name, 'figure_number': number, 'paper_label': label,
                       'sha256': sha256(target), **image})
    shared = Path(__file__).resolve().parent
    code = [package / 'plot_results.py', *sorted(shared.glob('*.py'))]
    manifest = {
        'format_version': 3, 'input_package': package.name, 'experiment': int(package.name.rsplit('-', 1)[1]),
        'inputs': inputs,
        'code': {str(path.relative_to(package.parent)): sha256(path) for path in code},
        'software': {'python': platform.python_version(), 'matplotlib': matplotlib.__version__,
                     'numpy': numpy.__version__, 'pillow': PIL.__version__},
        'figures': images, 'statistics': statistics,
        'input_evidence_unchanged': True, 'provider_calls': 0, 'database_connections': 0,
    }
    metadata = output / 'metadata'
    metadata.mkdir(exist_ok=True)
    (metadata / (package.name + '.json')).write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'experiment': manifest['experiment'], 'figures': len(images),
                      'output': str(output), 'input_evidence_unchanged': True}))
