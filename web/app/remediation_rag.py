import hashlib
import json
import math
import os
import re
from collections import Counter
import requests
from rag_corpus import active_collection
import hashlib
import json
import math
import os
import re
from collections import Counter

import requests
from rag_corpus import active_collection


QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/")
COLLECTION = os.getenv("RAG_COLLECTION", "wcag_act_examples")
VECTOR_SIZE = 384
MAX_ACT_CODE_CHARS = 5000
AXE_ACT_TERMS = {
    "aria-valid-attr-value": "ARIA state or property has valid value",
    "aria-required-attr": "Element with role attribute has required states and properties",
    "aria-allowed-attr": "ARIA attribute allowed",
    "html-has-lang": "HTML page has lang attribute",
    "html-lang-valid": "HTML page `lang` attribute has valid language tag",
    "image-alt": "Image has non-empty accessible name",
    "svg-img-alt": "SVG element with explicit role has non-empty accessible name",
    "link-name": "link has non-empty accessible name",
    "button-name": "button has non-empty accessible name",
    "label": "Form field has non-empty accessible name",
    "select-name": "Form field has non-empty accessible name",
    "frame-title": "Iframe element has non-empty accessible name",
    "document-title": "HTML page has non-empty title",
    "meta-viewport": "Meta viewport allows for zoom",
    "region": "page content is contained by landmarks",
    "landmark-one-main": "document has one main landmark",
    "color-contrast": "text has minimum contrast",
    "listitem": "list item has list parent",
    "page-has-heading-one": "page has level one heading",
    "nested-interactive": "interactive controls are not nested",
    "aria-valid-attr": "ARIA attribute is defined in WAI-ARIA",
    "aria-roles": "Role attribute has valid value",
    "aria-hidden-focus": "Element with aria-hidden has no content in sequential focus navigation",
    "scrollable-region-focusable": "Scrollable content can be reached with sequential focus navigation",
    "input-image-alt": "Image button has non-empty accessible name",
    "summary-name": "Summary element has non-empty accessible name",
    "aria-allowed-role": "ARIA role is allowed for the HTML element",
    "target-size": "pointer target has sufficient size or spacing",
    "empty-table-header": "table header has visible descriptive text",
    "landmark-contentinfo-is-top-level": "contentinfo landmark is outside other landmarks",
    "landmark-banner-is-top-level": "banner landmark is outside other landmarks",
    "landmark-main-is-top-level": "main landmark is outside other landmarks",
    "link-in-text-block": "inline link is distinguishable without color alone",
}


def _features(text):
    tokens = re.findall(r"[a-z0-9_.:-]+|</?[a-z][a-z0-9-]*", (text or "").lower())
    return tokens + [f"{left}|{right}" for left, right in zip(tokens, tokens[1:])]


def embed(text):
    """Deterministic local feature-hashing embedding: reproducible and token-free."""
    vector = [0.0] * VECTOR_SIZE
    for feature, count in Counter(_features(text)).items():
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        slot = int.from_bytes(digest, "big") % VECTOR_SIZE
        sign = 1 if digest[0] & 1 else -1
        vector[slot] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [round(value / norm, 7) for value in vector]












def prompt_context(items):
    oversized_rules = {item.get('rule_id') or item.get('rule_name') for item in items
                       if len(str(item.get('code') or '')) > MAX_ACT_CODE_CHARS}
    items = [item for item in items if (item.get('rule_id') or item.get('rule_name')) not in oversized_rules]
    if not items:
        return "No retrieved ACT examples were available."
    blocks = []
    for number, item in enumerate(items, 1):
        requirements = ", ".join(item.get("requirements") or []) or "Named accessibility rule guidance"
        role = "pattern to emulate" if item.get("expected") == "passed" else "counterexample to avoid"
        blocks.append(
            f"Accessibility evidence {number} — {item.get('rule_name')} ({item.get('expected')}, {role}; {requirements})\n"
            f"Provenance: {item.get('source') or 'W3C ACT Rules'}\n"
            f"Source: {item.get('rule_page')}\n"
            f"Applicability: {item.get('guidance') or 'Apply only to the measured concept; an example is not page certification.'}\n"
            f"Code example:\n{item.get('code', '')}"
        )
    return "\n\n".join(blocks)


def retrieval_query(axe_evidence, feedback="", lighthouse_evidence=()):
    rules = [str(item.get("rule") or "") for item in (axe_evidence or [])]
    # Lighthouse reuses these audit identifiers. Admit only identifiers with
    # an existing exact ACT mapping; textual similarity is not applicability.
    rules = list(dict.fromkeys(rules + [str(item.get('audit') or item.get('id') or '')
        for item in lighthouse_evidence if (item.get('audit') or item.get('id')) in AXE_ACT_TERMS]))
    aliases = [AXE_ACT_TERMS[rule] for rule in rules if rule in AXE_ACT_TERMS]
    severity = {'critical': 4, 'serious': 3, 'moderate': 2, 'minor': 1}
    prioritized = sorted(axe_evidence or [], key=lambda item: (
        severity.get(item.get('impact'), 0), len(item.get('nodes') or [])), reverse=True)
    priority = ','.join(dict.fromkeys(str(item.get('rule') or '') for item in prioritized))
    return " ".join([f"AXE_RULES={','.join(rules)}", f"AXE_PRIORITY={priority}", "HTML accessibility remediation", *rules, *aliases, json.dumps(axe_evidence or [], ensure_ascii=False), "LIGHTHOUSE="+json.dumps(list(lighthouse_evidence), ensure_ascii=False), feedback or ""])

def adaptive_example_limit(failures, baseline=4):
    """Allow complete pairs for measured concepts, bounded to twelve examples."""
    concepts = {AXE_ACT_TERMS[item.get('rule')] for item in failures or []
                if item.get('rule') in AXE_ACT_TERMS}
    return min(12, max(2, int(baseline), 2 * len(concepts)))

def status():
    try:
        response = requests.get(f"{QDRANT_URL}/collections/{active_collection(COLLECTION)}", timeout=2)
        if response.status_code == 404:
            return {"available": False, "count": 0, "message": "RAG-ACT corpus is not initialized. Synchronize the local examples before using retrieval; evaluation remains available."}
        response.raise_for_status()
        result = response.json().get("result") or {}
        count = int(result.get("points_count") or 0)
        return {"available": count > 0, "count": count, "message": "RAG-ACT: W3C ACT examples and source-attributed complementary guidance" if count else "RAG-ACT corpus is empty. Synchronize the local examples before using retrieval; evaluation remains available."}
    except (requests.RequestException, OSError, ValueError):
        return {"available": False, "count": 0, "message": "The local vector database is unavailable."}

def retrieve(query, limit=6, previously_supplied=()):
    if not query.strip():
        return []
    requested = max(1, min(12, int(limit)))
    # Ask for a wider lexical neighborhood, then favor distinct rules and both
    # outcomes so the prompt contains patterns as well as counterexamples.
    payload = {"query": embed(query), "limit": min(48, requested * 4), "with_payload": True}
    try:
        collection = active_collection(COLLECTION)
        response = requests.post(f"{QDRANT_URL}/collections/{collection}/points/query", json=payload, timeout=8)
        response.raise_for_status()
    except (requests.RequestException, OSError, ValueError):
        return []
    points = (response.json().get("result") or {}).get("points") or []
    vector_ranked = [{**(point.get("payload") or {}), "score": round(float(point.get("score") or 0), 4)} for point in points]
    # Feature hashing is reproducible but can confuse neighboring accessibility
    # concepts. Rerank the small local corpus lexically so exact Axe-to-ACT
    # terminology wins, while retaining vector results as a fallback.
    try:
        corpus=[]; offset=None; seen_offsets=set()
        while True:
            scroll={"limit":1000,"with_payload":True,"with_vector":False}
            if offset is not None: scroll['offset']=offset
            corpus_response=requests.post(f"{QDRANT_URL}/collections/{collection}/points/scroll",json=scroll,timeout=8)
            corpus_response.raise_for_status()
            page=corpus_response.json().get('result') or {}
            corpus.extend(page.get('points') or [])
            offset=page.get('next_page_offset')
            if offset is None: break
            if str(offset) in seen_offsets: raise ValueError('Repeated ACT corpus pagination cursor')
            seen_offsets.add(str(offset))
    except (requests.RequestException,ValueError):
        corpus=[]
    query_tokens=set(_features(query)); query_text=(query or "").casefold()
    lexical=[]
    for point in corpus:
        item=point.get("payload") or {}; name=str(item.get("rule_name") or ""); title=str(item.get("title") or "")
        name_tokens=set(_features(name)); title_tokens=set(_features(title)); requirement_tokens=set(_features(" ".join(item.get("requirements") or [])))
        score=6*len(query_tokens & name_tokens)+2*len(query_tokens & title_tokens)+len(query_tokens & requirement_tokens)
        if name and name.casefold() in query_text: score+=50
        if score: lexical.append({**item,"score":round(float(score),4)})
    lexical.sort(key=lambda item:item["score"],reverse=True)
    ranked=lexical or vector_ranked
    marker=re.search(r"AXE_RULES=([^\s]+)",query or "")
    requested_rules={rule for rule in (marker.group(1).split(",") if marker else []) if rule}
    if query.startswith('AXE_RULES=') and not requested_rules: return []
    if marker and not any(rule in AXE_ACT_TERMS for rule in requested_rules):
        return []
    expected_names={AXE_ACT_TERMS[rule].casefold() for rule in requested_rules if rule in AXE_ACT_TERMS}
    exact_ranked=[item for item in ranked if str(item.get("rule_name") or "").casefold() in expected_names]
    # When an exact Axe-to-ACT mapping is available, do not pad the prompt with
    # semantically neighboring but unrelated rules merely to meet top_k.
    if exact_ranked:
        ranked=exact_ranked
    elif expected_names:
        # No evidence is safer than an attractive but unrelated few-shot
        # example. Component reconstruction has its own curated knowledge; ACT
        # RAG is admitted only when the corpus matches a measured Axe concept.
        return []
    # Never feed a sliced HTML example to the model. Prefer complete smaller
    # examples; pair selection below abstains if either outcome is unavailable.
    ranked = [item for item in ranked if len(str(item.get('code') or '')) <= MAX_ACT_CODE_CHARS]
    priority_marker = re.search(r'AXE_PRIORITY=([^\s]+)', query or '')
    if priority_marker:
        concepts = list(dict.fromkeys(AXE_ACT_TERMS[rule].casefold()
            for rule in priority_marker.group(1).split(',') if rule in AXE_ACT_TERMS))
        order = {concept: index for index, concept in enumerate(concepts)}
        # Measured severity/affected-node count wins over a longer rule title's
        # lexical score. The explicit example budget and complete pairs remain.
        ranked.sort(key=lambda item: order.get(str(item.get('rule_name') or '').casefold(), len(order)))
    if previously_supplied:
        # At a measured plateau, expose another relevant concept instead of
        # spending the same bounded context on identical pairs indefinitely.
        prior = set(previously_supplied)
        ranked.sort(key=lambda item: item.get('rule_id') in prior)
    selected = []
    seen = set()
    # A passed example from one rule and a failed example from another produces
    # misleading few-shot context. Anchor the pair to the best matching rule.
    anchor = next((item.get('rule_id') for item in ranked if all(any(other.get('rule_id')==item.get('rule_id') and other.get('expected')==outcome for other in ranked) for outcome in ('passed','failed'))), None)
    if expected_names and anchor is None: return []
    if anchor is None: anchor=ranked[0].get('rule_id') if ranked else None
    for outcome in ("passed", "failed"):
        item = next((candidate for candidate in ranked if candidate.get("rule_id") == anchor and candidate.get("expected") == outcome), None)
        if item:
            selected.append(item)
            seen.add((item.get("rule_id"), item.get("expected")))
    if len(selected) >= requested:
        return selected[:requested]
    # Admit complete matched pairs for additional rules, not disconnected
    # examples that consume context without illustrating a correction.
    for rule_id in dict.fromkeys(item.get("rule_id") for item in ranked):
        if len(selected)+2>requested: break
        pair=[next((item for item in ranked if item.get("rule_id")==rule_id and item.get("expected")==outcome),None) for outcome in ("passed","failed")]
        if all(pair) and all((rule_id,item.get("expected")) not in seen for item in pair):
            selected.extend(pair)
            seen.update((rule_id,item.get("expected")) for item in pair)
    return selected

def retrieval_evidence(items, failures):
    names={AXE_ACT_TERMS[item.get("rule")] for item in failures if item.get("rule") in AXE_ACT_TERMS}
    covered={item.get("rule_name") for item in items}
    covered_normalized={str(name or '').casefold() for name in covered}
    pairs={item.get("rule_id") for item in items if {candidate.get("expected") for candidate in items if candidate.get("rule_id")==item.get("rule_id")} >= {"passed","failed"}}
    return {"requested_concepts":sorted(names),"covered_concepts":sorted(covered),"missing_concepts":sorted(name for name in names if name.casefold() not in covered_normalized),"unmapped_axe_rules":sorted({item.get('rule') for item in failures if item.get('rule') and item.get('rule') not in AXE_ACT_TERMS}),"matched_pairs":len(pairs),"examples":len(items),"retrieval_method":"exact Axe-to-ACT mapping + lexical reranking + local vector fallback","semantic_embedding":False}
