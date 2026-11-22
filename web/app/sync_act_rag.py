"""Synchronize approved W3C ACT passed/failed HTML examples into local Qdrant."""
import datetime
import hashlib
import io
import json
import uuid
import zipfile
import argparse
from rag_corpus import active_collection, write_json

import requests

from remediation_rag import COLLECTION, QDRANT_URL, VECTOR_SIZE, embed


INDEX_URL = "https://www.w3.org/WAI/content-assets/wcag-act-rules/testcases.json"
ARCHIVE_URL = "https://github.com/w3c/wcag-act-rules/archive/refs/heads/main.zip"


def build_case(item, archive, prefix, snapshot_sha256):
    if item.get("expected") not in {"passed", "failed"} or not item.get("approved"):
        return None
    archive_path = prefix + "content-assets/wcag-act-rules/" + item["relativePath"]
    try:
        code = archive.read(archive_path).decode("utf-8", errors="replace").strip()
    except KeyError:
        return None
    requirements = sorted(key for key, value in (item.get("ruleAccessibilityRequirements") or {}).items() if isinstance(value, dict))
    search_text = " ".join([item.get("ruleName", ""), item.get("testcaseTitle", ""), item.get("expected", ""), " ".join(requirements), code])
    point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, item["url"]))
    return {"id": point_id, "vector": embed(search_text), "payload": {"source":"W3C ACT Rules","source_index":INDEX_URL,"snapshot_sha256":snapshot_sha256,"license":"https://act-rules.github.io/pages/license/","retrieved_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"rule_id":item.get("ruleId"),"rule_name":item.get("ruleName"),"rule_page":item.get("rulePage"),"testcase_id":item.get("testcaseId"),"title":item.get("testcaseTitle"),"expected":item.get("expected"),"requirements":requirements,"code":code,"example_url":item.get("url")}}


def main(initialize_only=False, progress=None, include_complementary=True):
    progress = progress or (lambda phase, percent: None)
    existing = requests.get(f"{QDRANT_URL}/collections/{active_collection(COLLECTION)}", timeout=10)
    if existing.status_code != 404:
        existing.raise_for_status()
        if initialize_only and int((existing.json().get('result') or {}).get('points_count') or 0):
            raise ValueError('RAG-ACT already contains examples; initialization will not replace them.')
    progress('download', 10)
    downloaded = requests.get(ARCHIVE_URL, timeout=180)
    downloaded.raise_for_status()
    snapshot_sha256 = hashlib.sha256(downloaded.content).hexdigest()
    archive = zipfile.ZipFile(io.BytesIO(downloaded.content))
    prefix = archive.namelist()[0].split("/", 1)[0] + "/"
    cases = json.loads(archive.read(prefix + "content-assets/wcag-act-rules/testcases.json")).get("testcases") or []
    progress('prepare', 30)
    points = []
    eligible = 0
    for item in cases:
        if item.get('approved') and item.get('expected') in {'passed', 'failed'}:
            eligible += 1
        point = build_case(item, archive, prefix, snapshot_sha256)
        if point:
            points.append(point)
    if not points or len(points) != eligible:
        raise ValueError('The ACT snapshot is empty or missing approved HTML examples.')
    official = len(points)
    from remediation_rag_supplement import points as supplemental_points
    supplement = supplemental_points() if include_complementary else []
    points.extend(supplement)
    target = f'{COLLECTION}_snapshot_{uuid.uuid4().hex}'
    requests.put(f"{QDRANT_URL}/collections/{target}", json={"vectors":{"size":VECTOR_SIZE,"distance":"Cosine"}}, timeout=30).raise_for_status()
    # Do not mutate or delete the currently published collection, even on failure.
    for start in range(0, len(points), 64):
        requests.put(f"{QDRANT_URL}/collections/{target}/points?wait=true", json={"points":points[start:start+64]}, timeout=60).raise_for_status()
        progress('index', 40 + int(50 * min(start+64, len(points)) / len(points)))
    progress('verify', 95)
    response = requests.get(f"{QDRANT_URL}/collections/{target}", timeout=10)
    response.raise_for_status()
    if int(response.json()['result'].get('points_count') or 0) != len(points):
        raise ValueError('The new RAG-ACT collection did not retain every example.')
    result = {'collection':target,'points':len(points),'official':official,'complementary':len(supplement),
              'index_total':len(cases), 'index_approved':sum(bool(item.get('approved')) for item in cases),
              'index_eligible':eligible,
              'source':INDEX_URL,'snapshot':ARCHIVE_URL,'snapshot_sha256':snapshot_sha256,
              'synchronized_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    write_json('corpus.json', result)
    return result


if __name__ == '__main__':
    raise SystemExit('Initialize the corpus from the Knowledge GUI after approving acquisition.')
