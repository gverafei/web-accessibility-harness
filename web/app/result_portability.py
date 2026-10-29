import base64
import hashlib
import json
import os
import shutil
import re
import stat
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ARTIFACT_COLUMNS = (
    "source_snapshot_path", "response_source_path",
    "screenshot_path", "axe_raw_path", "lighthouse_raw_path",
    "wave_raw_path", "semantic_raw_path",
)
PROVENANCE_COLUMNS = {
    "id", "experiment_id", "source_result_id", "source_experiment_id",
    "provenance", "normalized_url", "evaluated_at", "cost_incurred_usd",
}


def ensure_http_scheme(value):
    value = (value or "").strip()
    if value.startswith("//"):
        return f"https:{value}"
    if "://" not in value:
        return f"https://{value}"
    return value


def normalize_url(value):
    value = ensure_http_scheme(value)
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        hostname = f"{hostname}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return urlunsplit((scheme, hostname, path, parsed.query, ""))


def evaluation_signature(settings, include_wave, include_semantic, provider, model, axe_standard):
    payload = {
        "axe_standard": axe_standard,
        "include_wave": bool(include_wave),
        "include_semantic": bool(include_semantic),
        "semantic_provider": provider if include_semantic else None,
        "semantic_model": model if include_semantic else None,
        "wave_report_type": settings.get("wave_report_type") if include_wave else None,
        "runtime": {
            key: settings.get(key) for key in (
                "page_load_timeout_ms", "network_idle_timeout_ms", "page_settle_delay_ms",
                "dom_stability_window_ms", "dom_stability_timeout_ms", "enable_lazy_load_scroll",
                "scroll_step_px", "scroll_delay_ms", "max_scroll_steps",
            )
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def copy_snapshot_evidence(source, target, allowed_root):
    """Keep frozen resources and viewport segments with their owning snapshot."""
    source = Path(source)
    target = Path(target)
    root = Path(allowed_root).resolve()

    def saved_file(path):
        resolved = path.resolve()
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError('Saved snapshot evidence is unavailable within the results directory.')
        return resolved

    package = Path(str(source) + '.resources.json')
    if package.exists():
        shutil.copy2(saved_file(package), str(target) + '.resources.json')

    descriptor = Path(str(source) + '.segments.json')
    if descriptor.exists():
        original = saved_file(descriptor).read_bytes()
        data = json.loads(original)
        for index, segment in enumerate(data['segments']):
            segment_path = Path(segment['path'])
            if not segment_path.is_absolute():
                segment_path = source.parent / segment_path
            segment_path = saved_file(segment_path)
            destination = Path(str(target) + f'.segment-{index}' + segment_path.suffix)
            shutil.copy2(segment_path, destination)
            segment['path'] = str(destination)
        # Only segment locations change; image bytes and capture metadata stay intact.
        Path(str(target) + '.segments.json').write_bytes(
            json.dumps(data, ensure_ascii=False).encode() if data['segments'] else original)


def copy_artifacts(result, destination_experiment_id, *, raw_root='/results/raw'):
    copied = dict(result)
    from accessibility_taxonomy.inventory import read_acquired, sidecar_path
    taxonomy = read_acquired(result.get('source_snapshot_path'))
    allowed_root = os.path.realpath(raw_root)
    destination = os.path.realpath(os.path.join(allowed_root, f"experiment_{destination_experiment_id}"))
    os.makedirs(destination, exist_ok=True)
    for column in ARTIFACT_COLUMNS:
        source = result.get(column)
        resolved = os.path.realpath(source) if source else ""
        if not resolved.startswith(f"{allowed_root}{os.sep}") or not os.path.isfile(resolved):
            copied[column] = None
            continue
        stem, extension = os.path.splitext(os.path.basename(resolved))
        target = os.path.join(destination, f"source_{result.get('id', 'import')}_{stem}{extension}")
        counter = 2
        while os.path.exists(target):
            target = os.path.join(destination, f"source_{result.get('id', 'import')}_{stem}_{counter}{extension}")
            counter += 1
        shutil.copy2(resolved, target)
        copied[column] = target
        if column == 'screenshot_path':
            copy_snapshot_evidence(resolved, target, allowed_root)
    if taxonomy and copied.get('source_snapshot_path'):
        sidecar_path(copied['source_snapshot_path']).write_text(json.dumps(taxonomy,ensure_ascii=False))
    return copied


def clone_result(cursor, source, destination_experiment_id, provenance, copy_files=True):
    copied = copy_artifacts(source, destination_experiment_id) if copy_files else dict(source)
    cursor.execute("SHOW COLUMNS FROM experiment_results")
    allowed = {row[0] if not isinstance(row, dict) else row["Field"] for row in cursor.fetchall()}
    columns = [key for key in copied if key in allowed and key not in PROVENANCE_COLUMNS]
    columns += ["source_result_id", "source_experiment_id", "provenance", "normalized_url", "evaluated_at", "cost_incurred_usd"]
    values = [copied.get(key) for key in columns[:-6]] + [
        source.get("source_result_id") or source.get("id"),
        source.get("source_experiment_id") or source.get("experiment_id"),
        provenance,
        normalize_url(source.get("url")),
        source.get("evaluated_at") or source.get("created_at"),
        0,
    ]
    quoted = ", ".join(f"`{column}`" for column in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    cursor.execute(
        f"INSERT INTO experiment_results (`experiment_id`, {quoted}) VALUES (%s, {placeholders})",
        [destination_experiment_id, *values],
    )
    return cursor.lastrowid


def encode_artifacts(result):
    artifacts = {}
    allowed_root = os.path.realpath("/results/raw")
    for column in ARTIFACT_COLUMNS:
        path = result.get(column)
        resolved = os.path.realpath(path) if path else ""
        if resolved.startswith(f"{allowed_root}{os.sep}") and os.path.isfile(resolved):
            with open(resolved, "rb") as file:
                artifacts[column] = {
                    "filename": os.path.basename(resolved),
                    "base64": base64.b64encode(file.read()).decode("ascii"),
                }
    return artifacts


def validate_portable_payload(payload):
    if not isinstance(payload, dict) or payload.get("format") != "warp-experiment" or payload.get("version") not in {3,4}:
        raise ValueError("unsupported format")
    if not isinstance(payload.get("experiment"), dict):
        raise ValueError("invalid experiment metadata")
    environments = payload.get("environment", [])
    results = payload.get("results")
    if not isinstance(environments, list) or any(not isinstance(row, dict) for row in environments):
        raise ValueError("invalid environment metadata")
    if not isinstance(results, list) or not results:
        raise ValueError("empty or invalid results")
    seen = set()
    for entry in results:
        if not isinstance(entry, dict) or not isinstance(entry.get("data"), dict):
            raise ValueError("invalid result")
        data = entry["data"]
        parsed = urlsplit(str(data.get("url") or ""))
        normalized = normalize_url(data.get("url"))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or not normalized or normalized in seen:
            raise ValueError("invalid or duplicate URL")
        seen.add(normalized)
        artifacts = entry.get("artifacts", {})
        if not isinstance(artifacts, dict) or any(key not in ARTIFACT_COLUMNS for key in artifacts):
            raise ValueError("invalid artifacts")
        for artifact in artifacts.values():
            if not isinstance(artifact, dict) or not isinstance(artifact.get("filename"), str):
                raise ValueError("invalid artifact")
            if payload['version'] == 3:
                if not isinstance(artifact.get('base64'), str):
                    raise ValueError('invalid artifact')
                base64.b64decode(artifact['base64'], validate=True)
            elif (not isinstance(artifact.get('member'), str) or
                  not artifact['member'].startswith('artifacts/') or
                  '\\' in artifact['member'] or '..' in artifact['member'].split('/') or
                  not re.fullmatch(r'[0-9a-f]{64}',str(artifact.get('sha256') or '')) or
                  not isinstance(artifact.get('size'), int) or artifact['size'] < 0):
                raise ValueError('invalid artifact member')
    return results


def validate_archive_artifacts(payload, archive, max_total_bytes=32*1024**3):
    """Validate v4 references and sizes before any database mutation/extraction."""
    if payload.get('version') != 4:
        return
    total, seen = 0, set()
    for entry in payload['results']:
        for artifact in entry.get('artifacts',{}).values():
            name=artifact['member']
            if name in seen:
                raise ValueError('duplicate artifact reference')
            seen.add(name)
            item=archive.getinfo(name)
            if item.is_dir() or stat.S_ISLNK(item.external_attr >> 16) or item.file_size != artifact['size']:
                raise ValueError('invalid artifact size or type')
            total += item.file_size
            if total > max_total_bytes:
                raise ValueError('uncompressed artifacts exceed the storage budget')
    if {item.filename for item in archive.infolist() if item.filename.startswith('artifacts/')} != seen:
        raise ValueError('unreferenced artifact members')


def decode_artifacts(result, artifacts, destination_experiment_id, archive=None):
    destination = os.path.realpath(f"/results/raw/experiment_{destination_experiment_id}")
    os.makedirs(destination, exist_ok=True)
    for column in ARTIFACT_COLUMNS:
        result[column] = None
        artifact = (artifacts or {}).get(column)
        if not artifact:
            continue
        filename = os.path.basename(artifact.get("filename") or f"{column}.bin")
        target = os.path.join(destination, f"import_{filename}")
        stem, extension = os.path.splitext(target)
        counter = 2
        while os.path.exists(target):
            target = f"{stem}_{counter}{extension}"
            counter += 1
        with open(target, "wb") as file:
            if artifact.get('member'):
                if archive is None:
                    raise ValueError('artifact archive is required')
                digest=hashlib.sha256()
                with archive.open(artifact['member']) as source:
                    while chunk := source.read(64*1024):
                        file.write(chunk); digest.update(chunk)
                if digest.hexdigest() != artifact['sha256']:
                    raise ValueError('artifact SHA-256 mismatch')
            else:
                file.write(base64.b64decode(artifact["base64"], validate=True))
        result[column] = target
    return result
