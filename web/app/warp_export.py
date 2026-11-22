"""Streaming .warp writer with bounded artifact RAM and small v4 manifests."""
import base64
import json
import zipfile
import hashlib
from pathlib import Path

from result_portability import ARTIFACT_COLUMNS, json_value
from accessibility_taxonomy.inventory import read_acquired

CHUNK_BYTES = 48 * 1024  # Multiple of three: base64 chunks concatenate exactly.


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=json_value).encode('utf-8')


def manifest_chunks(metadata, results, artifact_root='/results/raw'):
    """Same manifest contract as v3; never read/base64 a whole evidence file."""
    root = Path(artifact_root).resolve()
    yield b'{'
    for key, value in metadata.items():
        yield _json(key) + b':'
        yield _json(value) + b','
    yield b'"results":['
    for index, row in enumerate(results):
        if index:
            yield b','
        data = {key: value for key, value in row.items() if key not in ARTIFACT_COLUMNS}
        yield b'{"data":' + _json(data) + b',"artifacts":{'
        first = True
        for column in ARTIFACT_COLUMNS:
            if not row.get(column):
                continue
            path = Path(row[column]).resolve()
            if root not in path.parents or not path.is_file():
                continue
            if not first:
                yield b','
            first = False
            yield _json(column) + b':{"filename":' + _json(path.name) + b',"base64":"'
            with path.open('rb') as source:
                while chunk := source.read(CHUNK_BYTES):
                    yield base64.b64encode(chunk)
            yield b'"}'
        yield b'}}'
    yield b']}'


def portable_manifest(metadata, results, artifact_root='/results/raw'):
    """Files stay binary in ZIP; manifest records their size and SHA-256."""
    root = Path(artifact_root).resolve()
    entries, files = [], []
    for index, row in enumerate(results):
        data = {key: json_value(value) for key, value in row.items() if key not in ARTIFACT_COLUMNS}
        artifacts = {}
        for column in ARTIFACT_COLUMNS:
            if not row.get(column):
                continue
            path = Path(row[column]).resolve()
            if root not in path.parents or not path.is_file():
                continue
            digest = hashlib.sha256()
            with path.open('rb') as source:
                while chunk := source.read(CHUNK_BYTES):
                    digest.update(chunk)
            name = f'artifacts/{index}/{column}/{path.name}'
            artifacts[column] = {'filename':path.name, 'member':name,
                                 'size':path.stat().st_size, 'sha256':digest.hexdigest()}
            files.append((path, name))
        entry={'data':data,'artifacts':artifacts}
        taxonomy=read_acquired(row.get('source_snapshot_path'))
        if taxonomy: entry['taxonomy_inventory']=taxonomy
        entries.append(entry)
    return dict(metadata, version=4, results=entries), files


class _Output:
    """Nonseekable ZIP sink; drained after each small input chunk."""
    def __init__(self):
        self.pending = []
        self.offset = 0

    def write(self, value):
        self.pending.append(value)
        self.offset += len(value)
        return len(value)

    def tell(self):
        return self.offset

    def flush(self):
        pass

    def drain(self):
        chunks, self.pending = self.pending, []
        return chunks


def dataset_members(storage_key, dataset_root):
    root = Path(dataset_root).resolve()
    source = (root / storage_key).resolve()
    if source.parent != root or not source.is_dir():
        raise ValueError('The local dataset files are unavailable.')
    files = []
    for path in sorted(source.rglob('*')):
        if path.is_file() and path.name != '.warp-dataset.json':
            if source not in path.resolve().parents:
                raise ValueError('Dataset resources must stay inside the stored dataset.')
            files.append((path, f'dataset/{path.relative_to(source).as_posix()}'))
    return files


def archive_chunks(metadata, results, dataset_files=(), artifact_root='/results/raw'):
    output = _Output()
    if metadata.get('version') == 4:
        metadata, artifacts = portable_manifest(metadata, results, artifact_root)
        manifest = (_json(metadata),)
        members = [*artifacts, *dataset_files]
    else:
        manifest = manifest_chunks(metadata, results, artifact_root)
        members = dataset_files
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=1, allowZip64=True) as archive:
        with archive.open('experiment.json', 'w', force_zip64=True) as member:
            yield from output.drain()
            for chunk in manifest:
                member.write(chunk)
                yield from output.drain()
        yield from output.drain()
        for path, name in members:
            with archive.open(name, 'w', force_zip64=True) as member, Path(path).open('rb') as source:
                yield from output.drain()
                while chunk := source.read(CHUNK_BYTES):
                    member.write(chunk)
                    yield from output.drain()
            yield from output.drain()
    yield from output.drain()


def file_archive_chunks(manifest_name, metadata, members):
    """Stream a named manifest and binary members for another versioned format."""
    output = _Output()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=1, allowZip64=True) as archive:
        archive.writestr(manifest_name, _json(metadata))
        yield from output.drain()
        for path, name in members:
            with archive.open(name, 'w', force_zip64=True) as member, Path(path).open('rb') as source:
                yield from output.drain()
                while chunk := source.read(CHUNK_BYTES):
                    member.write(chunk)
                    yield from output.drain()
            yield from output.drain()
    yield from output.drain()
