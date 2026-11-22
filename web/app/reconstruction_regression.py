"""Measured area checkpoints; the assembled document remains the audit unit."""
from copy import deepcopy
from collections import Counter
import json
import re
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urljoin


def checkpoint_areas(state, candidate, raw_axe_path, plan, base_url=None):
    """Restore worse local inputs for the NEXT assembly, never fake its scores.

    An unattributable failure disables reuse: cross-area CSS/JS cannot safely
    be judged from an isolated fragment. Conversation history is preserved.
    """
    try:
        raw=json.loads(Path(raw_axe_path).read_text())
        violations=raw['violations']
        if not isinstance(violations,list): raise ValueError('Invalid Axe violations')
    except (OSError, ValueError, TypeError, KeyError):
        for entry in state.values():
            if isinstance(entry,dict): entry['reuse']=False
        return {"restored":[],"retained":[],"reason":"audit unavailable"}
    soup=BeautifulSoup(candidate,"html.parser")
    failures={task.get("key",task["area"]):0 for task in plan}; unknown=0
    for rule in violations:
        if 'best-practice' in rule.get('tags', []):
            continue
        for node in rule.get("nodes",[]):
            owners=set()
            for selector in node.get("target",[]):
                if not isinstance(selector,str): continue
                try: matches=soup.select(selector)
                except Exception: matches=[]
                for match in matches:
                    for ancestor in [match,*match.parents]:
                        identifier=ancestor.get("id") if hasattr(ancestor,"get") else None
                        area="main" if identifier=="content" else str(identifier or "").removeprefix("warp-")
                        if area in failures: owners.add(area); break
            if owners:
                for area in owners: failures[area]+=1
            else: unknown+=1
    outcome={"restored":[],"retained":[],"unattributed_failures":unknown,"area_failures":failures}
    for task in plan:
        area=task.get("key",task["area"]); entry=state.get(area,{})
        part=entry.get("part")
        if not part: continue
        protected=next((item for item in state.get('born_manifest',[]) if item['id']==area),None)
        source_soup=BeautifulSoup(protected['html'] if protected else task["source"],"html.parser")
        output_soup=BeautifulSoup(part["html"],"html.parser")
        source_text=Counter(re.findall(r'\w+',source_soup.get_text(' ',strip=True).casefold()))
        output_text=Counter(re.findall(r'\w+',output_soup.get_text(' ',strip=True).casefold()))
        missing=sum((source_text-output_text).values())/max(sum(source_text.values()),1)
        resources=lambda document: {(node.name,key,urljoin(base_url or '',node.get(key))) for node in document.select("a[href],img[src],form[action]") for key in ("href","src","action") if node.get(key)}
        required=resources(source_soup)
        missing_resources=len(required-resources(output_soup))/max(len(required),1)
        score=(failures[area],missing+missing_resources)
        improves=("best_score" not in entry or (all(value<=best for value,best in zip(score,entry["best_score"])) and score!=entry["best_score"]))
        if improves:
            entry["best_score"]=score; entry["best_part"]=deepcopy(part)
        elif any(value>best for value,best in zip(score,entry["best_score"])):
            entry["part"]=deepcopy(entry["best_part"])
            outcome["restored"].append(area)
        entry["reuse"]=not unknown and entry["best_score"][0]==0 and entry["best_score"][1]==0
        if entry["reuse"]: outcome["retained"].append(area)
    return outcome
