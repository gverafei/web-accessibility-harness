from __future__ import annotations
import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Mapping
import requests
TRANCO_STRATA = (
    ("rank_1_1000", "Global top 1,000", 1, 1_000),
    ("rank_1001_10000", "Very high popularity", 1_001, 10_000),
    ("rank_10001_100000", "High popularity", 10_001, 100_000),
    ("rank_100001_500000", "Medium popularity", 100_001, 500_000),
    ("rank_500001_1000000", "Popularity tail", 500_001, 1_000_000),
)
"""Official identified Tranco downloads and bounded ranking parsing."""


import csv
import hashlib
import io
import re
import zipfile
from collections.abc import Mapping

import requests

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
LIST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,100}$")

TRANCO_ORIGIN = "https://tranco-list.eu"

def fetch_latest_standard_list(session=requests):
    """Pin the latest standard list ID, then download that exact archived list."""
    try:
        id_response = session.get(f"{TRANCO_ORIGIN}/top-1m-id", timeout=30)
        id_response.raise_for_status()
        list_id = id_response.text.strip()
        if not LIST_ID_PATTERN.fullmatch(list_id):
            raise TrancoImportError("Tranco returned an invalid permanent list ID.")
        list_response = session.get(
            f"{TRANCO_ORIGIN}/download/{list_id}/1000000", timeout=120
        )
        list_response.raise_for_status()
    except TrancoImportError:
        raise
    except requests.RequestException as error:
        raise TrancoImportError("The latest standard Tranco list could not be downloaded.") from error
    if len(list_response.content) > MAX_UPLOAD_BYTES:
        raise TrancoImportError("The Tranco list exceeds the 100 MB download limit.")
    return list_response.content, f"tranco_{list_id}.csv", list_id

def fetch_pinned_standard_list(list_id: str, session=requests):
    """Download an already pinned Tranco list without selecting a newer release."""
    if not LIST_ID_PATTERN.fullmatch(list_id or ""):
        raise TrancoImportError("The stored Tranco list ID is invalid.")
    try:
        response = session.get(
            f"{TRANCO_ORIGIN}/download/{list_id}/1000000", timeout=120
        )
        response.raise_for_status()
    except requests.RequestException as error:
        raise TrancoImportError("The pinned Tranco list could not be downloaded.") from error
    if len(response.content) > MAX_UPLOAD_BYTES:
        raise TrancoImportError("The Tranco list exceeds the 100 MB download limit.")
    return response.content, f"tranco_{list_id}.csv"

def _csv_bytes(upload_bytes: bytes, filename: str) -> tuple[bytes, str]:
    if not upload_bytes:
        raise TrancoImportError("The Tranco list file is empty.")
    if len(upload_bytes) > MAX_UPLOAD_BYTES:
        raise TrancoImportError("The Tranco list exceeds the 100 MB upload limit.")
    if zipfile.is_zipfile(io.BytesIO(upload_bytes)):
        with zipfile.ZipFile(io.BytesIO(upload_bytes)) as archive:
            files = [item for item in archive.infolist() if not item.is_dir()]
            csv_files = [item for item in files if item.filename.lower().endswith(".csv")]
            if len(csv_files) != 1:
                raise TrancoImportError("A Tranco ZIP must contain exactly one CSV file.")
            if csv_files[0].file_size > MAX_UPLOAD_BYTES:
                raise TrancoImportError("The CSV inside the Tranco ZIP exceeds 100 MB.")
            return archive.read(csv_files[0]), csv_files[0].filename
    if not filename.lower().endswith(".csv"):
        raise TrancoImportError("Upload the Tranco CSV or its original ZIP archive.")
    return upload_bytes, filename

def parse_tranco(upload_bytes: bytes, filename: str) -> tuple[list[tuple[int, str]], dict]:
    csv_data, member_name = _csv_bytes(upload_bytes, filename)
    try:
        text = csv_data.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise TrancoImportError("The Tranco CSV must use UTF-8 encoding.") from error

    ranking: list[tuple[int, str]] = []
    seen_ranks: set[int] = set()
    seen_domains: set[str] = set()
    for line_number, row in enumerate(csv.reader(io.StringIO(text)), 1):
        if not row or not any(cell.strip() for cell in row):
            continue
        if line_number == 1 and row[0].strip().lower() == "rank":
            continue
        if len(row) != 2:
            raise TrancoImportError(f"Invalid Tranco row {line_number}: expected rank,domain.")
        try:
            rank = int(row[0].strip())
        except ValueError as error:
            raise TrancoImportError(f"Invalid rank on Tranco row {line_number}.") from error
        domain = row[1].strip().lower().rstrip(".")
        try:
            ascii_domain = domain.encode("idna").decode("ascii")
        except UnicodeError as error:
            raise TrancoImportError(f"Invalid domain on Tranco row {line_number}.") from error
        if rank < 1 or rank > 1_000_000 or rank in seen_ranks:
            raise TrancoImportError(f"Duplicate or out-of-range rank on Tranco row {line_number}.")
        if (not ascii_domain or len(ascii_domain) > 253 or "." not in ascii_domain
                or "/" in ascii_domain or ascii_domain in seen_domains):
            raise TrancoImportError(f"Duplicate or invalid domain on Tranco row {line_number}.")
        seen_ranks.add(rank)
        seen_domains.add(ascii_domain)
        ranking.append((rank, ascii_domain))
    ranking.sort()
    if not ranking:
        raise TrancoImportError("No valid ranked domains were found in the Tranco file.")
    return ranking, {
        "source_filename": filename,
        "csv_member": member_name,
        "list_sha256": hashlib.sha256(csv_data).hexdigest(),
        "frame_size": len(ranking),
    }

def classify_failure(message):
    """Assign a compact, reproducible operational category to an evaluator error."""
    value = (message or "").casefold()
    if any(term in value for term in ("timed out", "timeout", "time out")):
        return "timeout"
    if any(term in value for term in ("name_not_resolved", "dns", "getaddrinfo", "no such host")):
        return "dns_resolution"
    if any(term in value for term in ("certificate", "ssl", "tls", "cert_")):
        return "tls_certificate"
    if any(term in value for term in ("403", "429", "access denied", "blocked", "captcha")):
        return "access_restricted"
    if any(term in value for term in ("404", "410", "not found")):
        return "not_found"
    if any(term in value for term in ("500", "502", "503", "504", "server error")):
        return "remote_server_error"
    if any(term in value for term in ("connection refused", "connection reset", "connection closed")):
        return "connection_failure"
    return "other_evaluation_failure"


class TrancoImportError(ValueError):
    pass

def form_strata(form):
    """Freeze editable display labels without changing rank membership or IDs."""
    definitions = []
    for label, name, lower, upper in TRANCO_STRATA:
        display = str(form.get(f"tranco_label_{label}", name)).strip()
        if not display or len(display) > 120:
            raise TrancoImportError("Use a nonempty Tranco group name of at most 120 characters.")
        definitions.append((label, display, lower, upper))
    return tuple(definitions)

def _stratum_counts(value, definitions):
    """Accept researcher-defined counts, not example-specific sample limits."""
    labels = {label for label, _name, _lower, _upper in definitions}
    if isinstance(value, int) and not isinstance(value, bool):
        counts = dict.fromkeys(labels, value)
    elif isinstance(value, Mapping) and not set(value).difference(labels):
        counts = {label: value.get(label, 0) for label in labels}
    else:
        raise TrancoImportError("Use whole-number counts for the defined Tranco strata.")
    if any(isinstance(count, bool) or not isinstance(count, int) or count < 0
           for count in counts.values()):
        raise TrancoImportError("Tranco sample and reserve counts must be nonnegative whole numbers.")
    return counts

def sample_tranco(ranking, list_id: str, seed: str, sample_per_stratum: int | Mapping,
                  reserve_per_stratum: int | Mapping, *, strata_definitions=None):
    """Select exact targets; reserve requests use only remaining ranked domains."""
    if not LIST_ID_PATTERN.fullmatch(list_id):
        raise TrancoImportError("Enter the permanent Tranco list ID shown on tranco-list.eu.")
    if not seed or len(seed) > 100:
        raise TrancoImportError("Enter a sampling seed of at most 100 characters.")
    definitions = tuple(strata_definitions or TRANCO_STRATA)
    if len({label for label, _name, _lower, _upper in definitions}) != len(definitions):
        raise TrancoImportError("Tranco stratum labels must be unique.")
    if any(lower < 1 or upper > 1_000_000 or lower > upper
           for _label, _name, lower, upper in definitions):
        raise TrancoImportError("Tranco strata must have valid rank boundaries.")
    if any(left[3] >= right[2] for left, right in zip(definitions, definitions[1:])):
        raise TrancoImportError("Tranco strata must not overlap.")
    sample_counts = _stratum_counts(sample_per_stratum, definitions)
    reserve_counts = _stratum_counts(reserve_per_stratum, definitions)
    if not any(sample_counts.get(label, 0) for label, _name, _lower, _upper in definitions):
        raise TrancoImportError("Select at least one site from one Tranco popularity group.")

    candidates = []
    strata = []
    for label, display_name, lower, upper in definitions:
        selected_count = sample_counts.get(label, 0)
        reserve_count = reserve_counts.get(label, 0) if selected_count else 0
        pool = [(rank, domain) for rank, domain in ranking if lower <= rank <= upper]
        required = selected_count + reserve_count
        if len(pool) < selected_count:
            raise TrancoImportError(
                f"The uploaded list has only {len(pool)} domains in {label}; "
                f"{selected_count} are required."
            )
        pool.sort(key=lambda item: hashlib.sha256(
            f"warp-tranco-v2|{list_id}|{seed}|{label}|{item[0]}|{item[1]}".encode("utf-8")
        ).digest())
        selected = pool[:selected_count]
        reserves = pool[selected_count:min(required, len(pool))]
        for order, (rank, domain) in enumerate(selected, 1):
            candidates.append({
                "rank": rank, "domain": domain, "url": f"https://{domain}/",
                "stratum": label, "stratum_name": display_name,
                "role": "selected", "selection_order": order,
            })
        for order, (rank, domain) in enumerate(reserves, 1):
            candidates.append({
                "rank": rank, "domain": domain, "url": f"https://{domain}/",
                "stratum": label, "stratum_name": display_name,
                "role": "reserve", "selection_order": order,
            })
        strata.append({
            "label": label, "display_name": display_name,
            "rank_min": lower, "rank_max": upper,
            "frame_count": len(pool), "selected_count": len(selected),
            "reserve_count": len(reserves),
        })
    return candidates, strata

def plan_failed_replacements(candidates, failed_urls):
    """Select the next unused reserve in the same stratum for each failed primary."""
    failed = set(failed_urls)
    reserves = {}
    for item in candidates:
        if item.get("role") == "reserve":
            reserves.setdefault(item.get("stratum"), []).append(item)
    for pool in reserves.values():
        pool.sort(key=lambda item: item.get("selection_order") or 0)

    replacements = []
    for primary in candidates:
        if primary.get("role") not in {"selected", "selected_replacement"}:
            continue
        if primary.get("url") not in failed:
            continue
        pool = reserves.get(primary.get("stratum"), [])
        if not pool:
            continue
        replacement = pool.pop(0)
        replacements.append((primary, replacement))
    return replacements

def extend_ordered_reserves(ranking, list_id, seed, candidates, strata_labels,
                            batch_size=100, strata_definitions=None):
    """Append the next deterministic candidates from selected rank strata."""
    definitions = {label: (name, lower, upper) for label, name, lower, upper in
                   (strata_definitions or TRANCO_STRATA)}
    known_domains = {item.get("domain") for item in candidates}
    added = []
    for label in sorted(set(strata_labels)):
        if label not in definitions:
            continue
        display_name, lower, upper = definitions[label]
        pool = [(rank, domain) for rank, domain in ranking if lower <= rank <= upper]
        pool.sort(key=lambda item: hashlib.sha256(
            f"warp-tranco-v2|{list_id}|{seed}|{label}|{item[0]}|{item[1]}".encode("utf-8")
        ).digest())
        existing_orders = [
            int(item.get("selection_order") or 0) for item in candidates
            if item.get("stratum") == label
        ]
        next_order = max(existing_orders, default=0) + 1
        for rank, domain in pool:
            if domain in known_domains:
                continue
            candidate = {
                "rank": rank, "domain": domain, "url": f"https://{domain}/",
                "stratum": label, "stratum_name": display_name,
                "role": "reserve", "selection_order": next_order,
            }
            candidates.append(candidate)
            added.append(candidate)
            known_domains.add(domain)
            next_order += 1
            if sum(item.get("stratum") == label for item in added) >= batch_size:
                break
    return added

def expand_stratified_sample(ranking, list_id, seed, candidates, strata, current_urls,
                             target_per_stratum=100, reserve_per_stratum=100):
    """Add deterministic sampling slots while preserving all prior recovery history."""
    _stratum_counts(target_per_stratum, TRANCO_STRATA)
    _stratum_counts(reserve_per_stratum, TRANCO_STRATA)
    if target_per_stratum < 1:
        raise TrancoImportError("The expanded target must include at least one site per stratum.")
    if any(target_per_stratum > int(item["frame_count"]) for item in strata):
        raise TrancoImportError("The expanded target exceeds the available domains in a Tranco stratum.")

    urls = list(dict.fromkeys(current_urls))
    active = set(urls)
    definitions = {label: (name, lower, upper) for label, name, lower, upper in TRANCO_STRATA}
    known = {item.get("domain") for item in candidates}
    for stratum in strata:
        label = stratum["label"]
        current_target = int(stratum.get("selected_count") or 0)
        needed = max(0, target_per_stratum - current_target)
        if not needed:
            continue
        display_name, lower, upper = definitions[label]
        pool = [(rank, domain) for rank, domain in ranking if lower <= rank <= upper]
        pool.sort(key=lambda item: hashlib.sha256(
            f"warp-tranco-v2|{list_id}|{seed}|{label}|{item[0]}|{item[1]}".encode("utf-8")
        ).digest())
        by_domain = {item.get("domain"): item for item in candidates if item.get("stratum") == label}
        additions = []
        for rank, domain in pool:
            candidate = by_domain.get(domain)
            if candidate and candidate.get("role") != "reserve":
                continue
            url = f"https://{domain}/"
            if url in active:
                continue
            if candidate is None:
                candidate = {
                    "rank": rank, "domain": domain, "url": url,
                    "stratum": label, "stratum_name": display_name,
                    "role": "reserve", "selection_order": len(by_domain) + 1,
                }
                candidates.append(candidate)
                by_domain[domain] = candidate
                known.add(domain)
            candidate["role"] = "selected"
            candidate["selection_cohort"] = "expanded"
            additions.append(url)
            active.add(url)
            if len(additions) == needed:
                break
        if len(additions) != needed:
            raise TrancoImportError(f"The Tranco stratum {label} cannot supply the expanded target.")
        urls.extend(additions)
        stratum["selected_count"] = current_target + len(additions)

    for stratum in strata:
        label = stratum["label"]
        available = sum(1 for item in candidates if item.get("stratum") == label and item.get("role") == "reserve")
        missing = max(0, reserve_per_stratum - available)
        if missing:
            extend_ordered_reserves(ranking, list_id, seed, candidates, [label], missing)
        stratum["reserve_count"] = sum(
            1 for item in candidates if item.get("stratum") == label and item.get("role") == "reserve"
        )
    return urls, candidates, strata

def plan_failed_retries(candidates, failed_urls):
    """Return active failed candidates that have not used their one controlled retry."""
    failed = set(failed_urls)
    return [
        candidate for candidate in candidates
        if candidate.get("role") in {"selected", "selected_replacement"}
        and candidate.get("url") in failed
        and int(candidate.get("retry_count") or 0) < 1
    ]
