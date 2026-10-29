"""Reporting helpers for the Fathallah et al. AccessGuru taxonomy."""

import json
from pathlib import Path


from accessibility_taxonomy import RULES, CATALOG

LAYOUT_RULES = {key for key, row in RULES.items() if row['category'] == 'Layout'}
SYNTACTIC_RULES = {key for key, row in RULES.items() if row['category'] == 'Syntactic'}


def category_for_rule(rule_id):
    if rule_id in LAYOUT_RULES:
        return "Layout"
    if rule_id in SYNTACTIC_RULES:
        return "Syntactic"
    return "Unclassified"


def axe_taxonomy(raw_path):
    """Count affected elements (not only distinct rules) per category."""
    result = {name: {"count": None, "rules": [], "status": "not_assessed", "catalog_version": CATALOG["version"]} for name in ("Syntactic", "Layout", "Unclassified")}
    path = Path(raw_path or "")
    if not path.is_file():
        return result
    try:
        violations = json.loads(path.read_text(encoding="utf-8"))["violations"]
    except (OSError, ValueError, KeyError, TypeError):
        return result
    if not isinstance(violations, list) or any(not isinstance(v, dict) for v in violations):
        return result
    for category in result.values():
        category.update(count=0, status="assessed")
    for violation in violations:
        if 'best-practice' in violation.get('tags', []):
            continue
        rule_id = str(violation.get("id") or "unknown")
        category = category_for_rule(rule_id)
        instances = max(1, len(violation.get("nodes") or []))
        result[category]["count"] += instances
        result[category]["rules"].append({"rule": rule_id, "instances": instances,
            "impact": violation.get("impact"), "help": violation.get("help")})
    return result
