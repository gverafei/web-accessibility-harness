"""Component generation/assembly; intelligent planning lives in remediation_planner.

Generation is an LLM task per component with persistent history and explicit
ownership. The deterministic assembler owns the common document contract;
the outer worker evaluates the assembled page.
"""
import html
import json
import re
import time
from bs4 import BeautifulSoup
from born_content import bind_content, manifest_context, layout_only, READABLE_CONTENT_CSS, validate_layout_css, ensure_primary_heading
from born_components import COMPONENT_CSS


class ReconstructionBudgetStop(ValueError):
    """A controlled stop between paid calls, not an invalid candidate."""


def namespace_fragment(part, prefix):
    """Apply the ownership contract deterministically, including references."""
    soup=BeautifulSoup(part["html"],"html.parser")
    identifiers=[node["id"] for node in soup.select("[id]")]
    if len(identifiers)!=len(set(identifiers)):
        raise ValueError("Duplicate ids within one generated area")
    mapping={identifier:identifier if identifier.startswith(prefix) else prefix+identifier for identifier in identifiers}
    part['_id_map']=mapping
    for node in soup.find_all(True):
        if node.get("id"): node["id"]=mapping[node["id"]]
        for attribute in ("for","aria-labelledby","aria-describedby","aria-controls","aria-owns"):
            if node.get(attribute): node[attribute]=" ".join(mapping.get(value,value) for value in node[attribute].split())
        for attribute in ("href","data-bs-target"):
            value=node.get(attribute,"")
            if value.startswith("#") and value[1:] in mapping: node[attribute]="#"+mapping[value[1:]]
    for channel in ("css","javascript"):
        value=part.get(channel) or ""
        for old,new in sorted(mapping.items(),key=lambda item:len(item[0]),reverse=True):
            value=re.sub(r"#"+re.escape(old)+r"(?![\w-])","#"+new,value)
            if channel=='javascript':
                value=re.sub(r'(getElementById\s*\(\s*)([\'\"])'+re.escape(old)+r'\2',lambda match:match[1]+match[2]+new+match[2],value)
        part[channel]=value
    part["html"]=str(soup)
    return part


def assemble_areas(parts,title,language="en"):
    body=[]; css=[]; scripts=[]; ids=set()
    grouped={"header":[],"main":[],"footer":[]}
    # A label/control or fragment anchor can refer to another owned area.
    # Resolve only globally unambiguous ids; never guess between duplicates.
    cross_ids={}; ambiguous=set()
    for part in parts:
        for old,new in part.get('_id_map',{}).items():
            if old in cross_ids and cross_ids[old]!=new: ambiguous.add(old)
            cross_ids[old]=new
    cross_ids={old:new for old,new in cross_ids.items() if old not in ambiguous and old!='content'}
    for part in parts:
        area=part["area"]; fragment=part["html"]
        soup=BeautifulSoup(fragment,"html.parser")
        for node in soup.find_all(True):
            for attribute in ('for','aria-labelledby','aria-describedby','aria-controls','aria-owns'):
                if node.get(attribute): node[attribute]=' '.join(cross_ids.get(value,value) for value in node[attribute].split())
            for attribute in ('href','data-bs-target'):
                value=node.get(attribute,'')
                if value.startswith('#') and value[1:] in cross_ids: node[attribute]='#'+cross_ids[value[1:]]
        fragment=str(soup)
        if soup.select("html,head,body,base,script,style,main"):
            raise ValueError(f"Area {area} violated the fragment document contract")
        for node in soup.select("[id]"):
            if node["id"] in ids or node["id"]=="content": raise ValueError(f"Duplicate/global fragment id: {node['id']}")
            ids.add(node["id"])
        grouped[area].append(f'<div id="warp-{part["key"]}" data-warp-component="{part["key"]}">{fragment}</div>' if part.get("key") else fragment)
        channels={channel:part.get(channel) or '' for channel in ('css','javascript')}
        for old,new in sorted(cross_ids.items(),key=lambda item:len(item[0]),reverse=True):
            for channel,value in channels.items():
                value=re.sub(r'#'+re.escape(old)+r'(?![\w-])','#'+new,value)
                if channel=='javascript': value=re.sub(r'(getElementById\s*\(\s*)([\'\"])'+re.escape(old)+r'\2',lambda match:match[1]+match[2]+new+match[2],value)
                channels[channel]=value
        css.append(channels['css'])
        if soup.select('[data-warp-renderer]'): css.append(COMPONENT_CSS)
        if channels['javascript']: scripts.append(channels['javascript'])
    for area,fragments in grouped.items():
        if not fragments and area!="main": continue
        outer_id="content" if area=="main" else f"warp-{area}"
        body.append(f'<{area} id="{outer_id}"'+(' tabindex="-1"' if area=="main" else '')+f'>{"".join(fragments)}</{area}>')
    # Framework resources are owned by the assembler, never duplicated by areas.
    document=f'''<!doctype html><html lang="{html.escape(language or 'en',quote=True)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title or 'Accessible page')}</title><style>
body{{line-height:1.6}}img{{max-width:100%;height:auto}}:focus-visible{{outline:3px solid #18529d;outline-offset:3px}}.warp-skip{{position:absolute;left:-9999px}}.warp-skip:focus{{left:1rem;top:1rem;z-index:9999;background:white;color:#103b72;padding:.6rem}}
{READABLE_CONTENT_CSS}{''.join(css)}</style></head><body><a class="warp-skip" href="#content">Skip to main content</a>{''.join(body)}{''.join('<script>'+script+'</script>' for script in scripts)}</body></html>'''
    return ensure_primary_heading(document,title)


def regenerate_areas(plan,inventory,settings,model,temperature,tier,allowed,call_model,extract_inventory,retrieve_knowledge,parse_json,visual_reference,state,event):
    parts=[]; usage=[]; pinned=model
    for task in plan:
        area=task["area"]; key=task.get("key",area); local=extract_inventory(task["source"],inventory.get("base_url"))
        if state.get(key,{}).get("reuse"):
            parts.append(state[key]["part"])
            event("Regression guard","area_retained",f"Retained measured {area} component {key}; the assembled page will be audited again",{"area":area,"component":key})
            continue
        if sum(item["cost_usd"] for item in usage)>=state.get("remaining_budget",float("inf")) or time.monotonic()>=state.get("deadline",float("inf")):
            raise ReconstructionBudgetStop("Fragment reconstruction stopped before an area call at the configured cost/time budget; partial pages are not published")
        if area=="main" and not task.get("key"):
            local["dynamic_images"]=inventory.get("dynamic_images",[])
            local["media_assets"]=inventory.get("media_assets",[])
        knowledge=retrieve_knowledge(local,"source")
        prompt=f'''You are the {area} reconstruction agent in a born-accessible page team. Return JSON with html, css, javascript, rationale. Generate ONLY your assigned area, not a complete document. The assembler supplies document metadata and landmarks; supply self-contained styles and native behavior. Do not emit those root elements, html, head, body, base, script or style tags. Use self-contained responsive styling, semantic HTML and native controls; minimalism, readable contrast, keyboard operation and no autoplay. Preserve every assigned text, link destination, image and form action/method/name/value/option. Do not summarize or invent titles. A carousel may become a static list of all slides, never a single slide that discards the rest. Keep images uncropped if they contain text. Prefix all local ids with {task['prefix']}; target global skip links at #content. Scope custom CSS to {'#content' if area=='main' else '#warp-'+area}. Put only necessary local behavior in javascript. Other agents own other areas: do not duplicate their content. Use the common screenshot as visual context, not permission to copy other areas.
Page: {inventory.get('title')} · language {inventory.get('language')}
Assigned area inventory: {json.dumps(local,ensure_ascii=False)}
Relevant component knowledge: {json.dumps(knowledge,ensure_ascii=False)}
Previous assembled-page feedback: {state.get('feedback','First generation')}
Retrieved W3C ACT examples (whole-page measured concepts; apply only if relevant to your assigned area): {state.get('act_grounding','No ACT examples supplied')}
Previous area output: {json.dumps(state.get(key,{}).get('part',{}),ensure_ascii=False)}'''
        prompt+=f"\nComponent identity: {key}. Scope CSS to #warp-{key} when this is a component task. Assigned rationale: {task.get('reason')}. Do not duplicate the global page assets; use only the assigned inventory."
        protected=next((item for item in state.get('born_manifest',[]) if item['id']==key),None)
        if protected:
            slot_rule='containing your internal semantic composition and every empty owned unit reference' if protected.get('require_composition') else 'which is EMPTY'
            prompt=f'''You are a component layout specialist in ONE coordinated born-accessible page. Return JSON with html, css, javascript, rationale. The assembler owns document landmarks and all source content. Return ONLY a layout fragment containing exactly one div/section/article data-warp-slot="{key}" {slot_rule}. Never rewrite, summarize, duplicate or hide source content. No root document/landmark tags or scripts/styles. Use restrained responsive spacing and responsive containers, no clipped/fixed-height content, no solid-color block backgrounds. Other areas share the same typography and neutral background; scope local CSS to #warp-{key}. No application-specific JavaScript. Original widget content is rendered statically and native form submissions are retained by the content assembler.
GLOBAL ARCHITECTURE AND READING ORDER: {manifest_context(state['born_manifest'])}
YOUR OWNED CONTENT BLOCK: {manifest_context([protected])}
Relevant framework knowledge: {json.dumps(knowledge,ensure_ascii=False)}
Measured feedback: {state.get('feedback','First generation')}
ACT evidence (apply only where relevant): {state.get('act_grounding','None')}
Previous owned layout: {layout_only(state.get(key,{}).get('part',{}).get('html',''))}'''
            if protected.get('composition_units'):
                from born_composition import COMPOSITION_INSTRUCTION
                prompt+='\n'+COMPOSITION_INSTRUCTION
        if len(prompt)>180000: raise ValueError(f"Area {area} exceeds its context budget; no truncated fragment was sent")
        event("Area coordinator","area_generate",f"Assigned {area} component {key} to Generator {pinned}; content, assets and id namespace are isolated",{"area":area,"component":key,"model":pinned})
        references=visual_reference if isinstance(visual_reference,list) else [visual_reference] if visual_reference else []
        messages=state.get(key,{}).get("messages",[])+[{"role":"user","content":[{"type":"text","text":prompt},*references] if references else prompt}]
        generated,ti,to,cost,seconds,actual=call_model(settings,pinned,prompt,True,temperature,tier,allowed,messages)
        event(f"{area.title()} reconstruction agent","area_generated",f"Received {area} component {key} output from {actual}: {ti+to} tokens, ${cost:.6f}; validating its contract",{"area":area,"component":key,"model":actual,"input_tokens":ti,"output_tokens":to,"cost_usd":cost,"seconds":seconds})
        if pinned.startswith("openrouter/"): pinned=actual
        part=parse_json(generated); part["area"]=area
        if protected:
            validate_layout_css(part.get('css',''))
            if part.get('javascript','').strip(): raise ValueError('Protected content layout must not invent application JavaScript')
            part['html']=bind_content(part.get('html',''),[protected],fragment=True)
        if task.get("key"): part["key"]=key
        if not part.get("html"): raise ValueError(f"Area {area} returned no fragment")
        # A redundant owned-area wrapper is losslessly removable. Foreign
        # document roots/scripts still fail the assembler contract.
        fragment=BeautifulSoup(part["html"],"html.parser")
        for wrapper in fragment.find_all(area): wrapper.unwrap()
        # Inline assets belong in the JSON asset channels. Relocate rather
        # than discard them; external scripts are not silently executed.
        for style in fragment.find_all("style"):
            part["css"]=(part.get("css") or "")+"\n"+style.get_text()
            style.decompose()
        for script in fragment.find_all("script"):
            if script.get("src"): raise ValueError(f"Area {area} supplied an unowned external script")
            part["javascript"]=(part.get("javascript") or "")+"\n"+script.get_text()
            script.decompose()
        part["html"]=str(fragment)
        namespace_fragment(part,task["prefix"])
        state.setdefault(key,{}).update({"messages":messages+[{"role":"assistant","content":generated}],"part":part})
        parts.append(part); usage.append({"role":f"{area.title()} reconstruction agent · {key}","component":key,"model":actual,"input_tokens":ti,"output_tokens":to,"cost_usd":cost,"seconds":seconds,"prompt":prompt})
    event("Document assembler","area_assemble",f"Joining {len(parts)} regenerated areas with one shared framework and document contract",{"areas":[part["area"] for part in parts]})
    return assemble_areas(parts,inventory.get("title"),inventory.get("language")),usage,pinned
