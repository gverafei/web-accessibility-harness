"""Conservative deterministic fidelity screening; no fabricated interaction evidence."""
from collections import Counter
import re
import json

VERSION='replay-admission-v8'


def control_coverage(original, replayed):
    """Match visible controls once; extra accessible label text is not loss.

    This screen measures presence. Destination/submission contracts remain
    independently protected; these strings cannot certify task equivalence.
    """
    normalize = lambda value: '|'.join(' '.join(part.split()) for part in value.split('|', 2))
    before, after = Counter(map(normalize, original)), Counter(map(normalize, replayed))
    exact = before & after
    matched = sum(exact.values()); before -= exact; after -= exact
    for key, count in sorted(before.items(), key=lambda item: -len(item[0])):
        parts = key.split('|', 2)
        if len(parts) != 3 or parts[0] not in ('A', 'BUTTON', 'SUMMARY'):
            continue
        for candidate, remaining in list(after.items()):
            observed = candidate.split('|', 2)
            if not remaining or len(observed) != 3 or parts[:2] != observed[:2]:
                continue
            # Preserve the original label as a contiguous word sequence.
            old, new = re.findall(r'\w+', parts[2].casefold()), re.findall(r'\w+', observed[2].casefold())
            if old and not any(new[i:i+len(old)] == old for i in range(len(new)-len(old)+1)):
                continue
            used = min(count, remaining); matched += used; count -= used; after[candidate] -= used
            if not count: break
    return matched / max(1, len(original)) if original else 1.

def compare(original,replayed):
    if not original or not replayed:
        return {'version':VERSION,'status':'review_required','reasons':['missing_visible_evidence'],'metrics':{}}
    if replayed.get('visibility_version') and original.get('visibility_version')!=replayed['visibility_version']:
        return {'version':VERSION,'status':'review_required','reasons':['incompatible_visible_evidence_policy'],'metrics':{},'scope':'Original and replay require compatible observed visibility evidence; legacy counts are not recomputed silently'}
    def overlap(a,b):
        a,b=Counter(a),Counter(b)
        return sum((a&b).values())/max(1,sum(a.values()))
    tokens=lambda s:re.findall(r'\w+',s.casefold())
    otext=original.get('text','');rtext=replayed.get('text','')
    coverage=overlap(tokens(otext),tokens(rtext))
    controls=control_coverage(original.get('controls',[]),replayed.get('controls',[]))
    image_count=original.get('visible_images',0);rendered_images=replayed.get('visible_images',0)
    reasons=[]
    native_before=original.get('native_control_reference')
    native_after=replayed.get('native_control_reference')
    native_coverage=None
    if native_before and native_after and native_before.get('version')==native_after.get('version')=='observed-native-control-state-v1':
        def native_key(record):
            # Paths are restoration locators, not a browser state or task
            # contract. Anonymous controls may move with an equivalent wrapper;
            # their complete signatures/states and multiplicity still must match.
            return json.dumps({'identity':record.get('id'),'signature':record.get('signature'),'state':record.get('state')},sort_keys=True,separators=(',',':'))
        before=Counter(map(native_key,native_before.get('records',[])))
        after=Counter(map(native_key,native_after.get('records',[])))
        native_coverage=sum((before&after).values())/max(1,sum(before.values())) if before else 1.
        if before-after:reasons.append('native_control_state_changed')
    if len(otext)>=80 and len(rtext)<40:reasons.append('blank_replay')
    if len(tokens(otext))>=15 and coverage<.8:reasons.append('visible_content_loss')
    if controls<.9:reasons.append('essential_control_loss')
    if image_count and rendered_images<image_count*.8:reasons.append('visible_image_loss')
    if rendered_images and replayed.get('broken_images',0)/rendered_images>.2:reasons.append('broken_visible_resources')
    if original.get('visible_media',0)>replayed.get('visible_media',0):reasons.append('visible_media_loss')
    if replayed.get('broken_media',0):reasons.append('broken_visible_media')
    uncertain=[]
    deferred=[d for d in replayed.get('media_descriptors',[]) if d.get('state')=='deferred']
    if deferred:
        if original.get('media_evidence_version') not in ('observed-media-state-v2','observed-media-state-v3','observed-media-state-v4'):
            uncertain.append('missing_original_deferred_media_evidence')
        else:
            key=lambda d:json.dumps(d.get('identity'),sort_keys=True,separators=(',',':'))
            before=Counter(key(d) for d in original.get('media_descriptors',[]) if d.get('state')=='deferred')
            if Counter(map(key,deferred))-before:reasons.append('newly_deferred_media')
    unbuffered=[d for d in replayed.get('media_descriptors',[]) if d.get('state')=='unbuffered']
    if unbuffered:
        if original.get('media_evidence_version') not in ('observed-media-state-v3','observed-media-state-v4'):
            uncertain.append('missing_original_unbuffered_media_evidence')
        else:
            key=lambda d:json.dumps(d.get('identity'),sort_keys=True,separators=(',',':'))
            valid=lambda d:(d.get('media_source') or {}).get('version')=='observed-media-source-v1' and (d.get('media_source') or {}).get('ready_state')=='open' and (d.get('media_source') or {}).get('buffers')==0
            before=Counter(key(d) for d in original.get('media_descriptors',[]) if d.get('state')=='unbuffered' and valid(d))
            if any(not valid(d) for d in unbuffered) or Counter(map(key,unbuffered))-before:reasons.append('newly_unbuffered_media')
    if not reasons and len(otext)<40 and not image_count:uncertain.append('insufficient_visible_content')
    metadata=[d for d in replayed.get('media_descriptors',[]) if d.get('state')=='metadata']
    original_metadata=[d for d in original.get('media_descriptors',[]) if d.get('state')=='metadata']
    if metadata or original_metadata:
        if original.get('media_evidence_version')!='observed-media-state-v4':
            uncertain.append('missing_original_worker_metadata_evidence')
        else:
            def metadata_key(d):
                return json.dumps({k:d.get(k) for k in ('identity','src_object_kind','ready_state','network_state','current_time','paused','error','video_width','video_height','buffered_ranges')},sort_keys=True)
            if Counter(map(metadata_key,metadata))!=Counter(map(metadata_key,original_metadata)):
                reasons.append('worker_metadata_state_changed')
    return {'version':VERSION,'status':'rejected' if reasons else 'review_required' if uncertain else 'admitted',
      'reasons':reasons+uncertain,'metrics':{'text_coverage':coverage,'control_coverage':controls,
        'original_images':image_count,'replay_images':rendered_images,'broken_images':replayed.get('broken_images',0),'original_media':original.get('visible_media',0),'replay_media':replayed.get('visible_media',0),'broken_media':replayed.get('broken_media',0),'deferred_media':replayed.get('deferred_media',0),'unbuffered_media':replayed.get('unbuffered_media',0),'metadata_media':replayed.get('metadata_media',0),'native_control_state_coverage':native_coverage},
      'thresholds':{'text_coverage':.8,'control_coverage':.9,'image_coverage':.8,'maximum_broken_fraction':.2},
      'warnings':(['script_errors_require_agent_inspection'] if replayed.get('script_errors') else [])+(['unbuffered_original_media_preserved_playback_not_assessed'] if unbuffered and not reasons and not uncertain else []),
      'scope':'Visible content, visible resources and essential control presence; server-side tasks require separate evaluation.'}
