import csv
import hashlib
import io
import json
import os
import shutil
import stat
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote


DATASET_ROOT = Path(os.getenv("DATASET_ROOT", "/datasets"))
MAX_UNCOMPRESSED_BYTES = 1_500_000_000
MAX_SINGLE_FILE_BYTES = 100_000_000
MANIFEST_FIELDS = {
    "path", "observation_id", "pair_id", "condition", "stratum", "expected_label"
}


class DatasetImportError(ValueError):
    pass


def safe_relative_path(value):
    normalized = str(value or "").replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if (
        not normalized or path.is_absolute() or ".." in path.parts
        or (len(path.parts) > 0 and ":" in path.parts[0])
    ):
        raise DatasetImportError(f"Unsafe dataset path: {value}")
    return path.as_posix()


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact_observation_name(relative_path, limit=120):
    """Keep imported HTML recognizable without exposing an unwieldy full path."""
    parts = PurePosixPath(relative_path).parts
    lowered = [part.casefold() for part in parts]
    if len(parts) >= 3 and lowered[0] == "html" and lowered[1].startswith("site-"):
        site = lowered[1].replace("site-", "Site ", 1)
        filename = PurePosixPath(parts[-1]).stem.casefold()
        if "generated" in lowered and len(parts) >= 6:
            generated_at = lowered.index("generated")
            if len(parts) > generated_at + 3:
                model_key = lowered[generated_at + 1]
                model = {"gpt": "GPT-4o", "gemini": "Gemini"}.get(
                    model_key, parts[generated_at + 1].replace("-", " ").title()
                )
                representation_key = lowered[generated_at + 2]
                representation = {"html": "HTML", "markdown": "Markdown"}.get(
                    representation_key, parts[generated_at + 2].replace("-", " ").title()
                )
                template = "Template" if filename == "template-yes" else "No template"
                return f"{site} · {model} – {representation} – {template}"
        if filename == "manual-correction":
            return f"{site} · Manual correction"
        if filename == "original":
            return f"{site} · Original"
    label = " / ".join(parts[-3:])
    if len(label) <= limit:
        return label
    suffix = label[-(limit - 2):]
    return f"…/{suffix.lstrip('/')}"


def extract_archive(upload, destination):
    try:
        archive = zipfile.ZipFile(upload.stream)
    except (zipfile.BadZipFile, OSError) as exc:
        raise DatasetImportError("The uploaded ZIP file is not valid.") from exc
    members = [item for item in archive.infolist() if not item.is_dir()]
    total_size = sum(item.file_size for item in members)
    if total_size > MAX_UNCOMPRESSED_BYTES:
        raise DatasetImportError("The uncompressed dataset is too large.")
    for item in members:
        if item.file_size > MAX_SINGLE_FILE_BYTES:
            raise DatasetImportError(f"Dataset file is too large: {item.filename}")
        if stat.S_ISLNK(item.external_attr >> 16):
            raise DatasetImportError(f"Symbolic links are not allowed: {item.filename}")
        relative = safe_relative_path(item.filename)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(item) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def store_individual_files(uploads, destination):
    used = set()
    for upload in uploads:
        if not upload or not upload.filename:
            continue
        name = safe_relative_path(Path(upload.filename).name)
        if Path(name).suffix.lower() not in {".html", ".htm"}:
            raise DatasetImportError("Individual uploads must be HTML files.")
        if name.casefold() in used:
            raise DatasetImportError(f"Duplicate file name: {name}")
        used.add(name.casefold())
        upload.save(destination / name)


def read_manifest(destination, external_manifest=None):
    # New uploads require no manifest. This argument remains available for
    # programmatic/legacy imports, but CSV files found inside an ordinary ZIP
    # are treated as regular files and never change which HTML is evaluated.
    if not external_manifest or not external_manifest.filename:
        return None
    raw = external_manifest.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    fields = set(reader.fieldnames or ())
    if "path" not in fields:
        raise DatasetImportError("The manifest must contain a path column.")
    unknown = fields - MANIFEST_FIELDS
    if unknown:
        raise DatasetImportError(f"Unknown manifest columns: {', '.join(sorted(unknown))}")
    rows = []
    seen = set()
    for number, row in enumerate(reader, start=2):
        relative = safe_relative_path(row.get("path"))
        if relative.casefold() in seen:
            raise DatasetImportError(f"Duplicate manifest path on row {number}: {relative}")
        seen.add(relative.casefold())
        path = destination / relative
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm"}:
            raise DatasetImportError(f"Manifest HTML file was not found: {relative}")
        label = (row.get("expected_label") or "").strip()
        if label and label not in {"0", "1"}:
            raise DatasetImportError(f"expected_label must be 0, 1, or empty on row {number}.")
        rows.append({key: (row.get(key) or "").strip() for key in MANIFEST_FIELDS})
        rows[-1]["path"] = relative
    return rows


def import_dataset(archive, html_files, manifest, title, resource_policy):
    if resource_policy not in {"isolated", "external"}:
        resource_policy = "isolated"
    storage_key = uuid.uuid4().hex
    destination = DATASET_ROOT / storage_key
    destination.mkdir(parents=True, exist_ok=False)
    try:
        supplied_html = [item for item in html_files if item and item.filename]
        if archive and archive.filename and supplied_html:
            raise DatasetImportError("Choose either one ZIP or individual HTML files, not both.")
        if archive and archive.filename:
            extract_archive(archive, destination)
        else:
            store_individual_files(supplied_html, destination)
        html_paths = sorted(
            path for path in destination.rglob("*")
            if path.is_file() and path.suffix.lower() in {".html", ".htm"}
        )
        if not html_paths:
            raise DatasetImportError("The dataset does not contain HTML files.")
        manifest_rows = read_manifest(destination, manifest)
        if manifest_rows is None:
            manifest_rows = [
                {"path": path.relative_to(destination).as_posix(), "observation_id": "",
                 "pair_id": "", "condition": "", "stratum": "", "expected_label": ""}
                for path in html_paths
            ]
        observations = []
        dataset_digest = hashlib.sha256()
        for index, row in enumerate(manifest_rows, start=1):
            path = destination / row["path"]
            digest = file_sha256(path)
            dataset_digest.update(row["path"].encode("utf-8"))
            dataset_digest.update(digest.encode("ascii"))
            observations.append({
                **row,
                "observation_id": row["observation_id"] or row["path"],
                "display_name": compact_observation_name(row["path"]),
                "content_sha256": digest,
                "served_url": f"http://dataset-server:8080/{storage_key}/{quote(row['path'])}",
            })
        metadata = {
            "format": "warp-html-dataset", "version": 1, "title": title,
            "storage_key": storage_key, "resource_policy": resource_policy,
            "content_sha256": dataset_digest.hexdigest(), "observations": len(observations),
        }
        (destination / ".warp-dataset.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )
        return metadata, observations
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def remove_dataset(storage_key):
    if storage_key and len(storage_key) == 32 and storage_key.isalnum():
        shutil.rmtree(DATASET_ROOT / storage_key, ignore_errors=True)


def clear_dataset_storage():
    if not DATASET_ROOT.is_dir():
        return
    for path in DATASET_ROOT.iterdir():
        if path.is_dir() and len(path.name) == 32 and path.name.isalnum():
            shutil.rmtree(path, ignore_errors=True)


def add_dataset_to_warp(archive, storage_key):
    source = (DATASET_ROOT / storage_key).resolve()
    if not source.is_dir() or source.parent != DATASET_ROOT.resolve():
        raise DatasetImportError("The local dataset files are unavailable.")
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.name != ".warp-dataset.json":
            archive.write(path, f"dataset/{path.relative_to(source).as_posix()}")


def import_dataset_from_warp(archive, descriptor, title):
    """Restore a packaged dataset after validating every declared observation hash."""
    storage_key = uuid.uuid4().hex
    destination = DATASET_ROOT / storage_key
    destination.mkdir(parents=True, exist_ok=False)
    try:
        members = [item for item in archive.infolist() if not item.is_dir() and item.filename.startswith("dataset/")]
        if not members:
            raise DatasetImportError("The packaged local dataset is empty.")
        if sum(item.file_size for item in members) > MAX_UNCOMPRESSED_BYTES:
            raise DatasetImportError("The packaged local dataset is too large.")
        for item in members:
            relative = safe_relative_path(item.filename[len("dataset/"):])
            if item.file_size > MAX_SINGLE_FILE_BYTES or stat.S_ISLNK(item.external_attr >> 16):
                raise DatasetImportError(f"Invalid packaged dataset file: {relative}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

        observations = []
        digest = hashlib.sha256()
        for index, row in enumerate(descriptor.get("observations") or [], start=1):
            relative = safe_relative_path(row.get("path"))
            path = destination / relative
            actual_hash = file_sha256(path) if path.is_file() else None
            if actual_hash != row.get("content_sha256"):
                raise DatasetImportError(f"Packaged HTML hash mismatch: {relative}")
            digest.update(relative.encode("utf-8"))
            digest.update(actual_hash.encode("ascii"))
            observations.append({
                "path": relative,
                "observation_id": row.get("observation_id") or f"observation-{index:04d}",
                "display_name": row.get("display_name") or compact_observation_name(relative),
                "pair_id": row.get("pair_id") or "",
                "condition": row.get("condition") or "",
                "stratum": row.get("stratum") or "",
                "expected_label": str(row.get("expected_label")) if row.get("expected_label") in {0, 1, "0", "1"} else "",
                "content_sha256": actual_hash,
                "served_url": f"http://dataset-server:8080/{storage_key}/{quote(relative)}",
            })
        if not observations or digest.hexdigest() != descriptor.get("content_sha256"):
            raise DatasetImportError("The packaged dataset manifest does not match its files.")
        metadata = {
            "format": "warp-html-dataset", "version": 1, "title": title,
            "storage_key": storage_key,
            "resource_policy": descriptor.get("resource_policy") if descriptor.get("resource_policy") in {"isolated", "external"} else "isolated",
            "content_sha256": digest.hexdigest(), "observations": len(observations),
        }
        (destination / ".warp-dataset.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return metadata, observations
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
