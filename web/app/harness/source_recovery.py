"""One verified dynamic-context alternative; response remains the primary source."""
from .source_preparation import prepare
from .capture_admission import assess as admission

def recover(store,environment,capture,source,baseline,check,campaign,identity,config,verification=None):
    reasons=set(check['data'].get('reasons',[]))
    # A response startup may reveal a deferred player absent from the acquired
    # state. Try the captured DOM once; the same admission still rejects any
    # added/degraded media. This does not authorize recovery of broken bytes.
    allowed={'visible_content_loss','essential_control_loss','visible_image_loss','visible_media_loss','newly_deferred_media','native_control_state_changed','source_measurement_not_repeatable'}
    if 'blank_replay' in reasons:
        # A valid acquired application can render blank from its response
        # shell. This is not permission to recover an originally blank or
        # blocked source, nor a workaround for missing frozen resources.
        data=capture['data'];visible=data.get('visible') or {}
        rendered=store.read_blob(data['rendered_id']).decode()
        if ((len(visible.get('text',''))>=80 or len(visible.get('controls',[]))>=5)
                and admission(rendered,data)['status']=='passed'):
            allowed.add('blank_replay')
    visual=(isinstance(verification,dict) and verification.get('kind')=='evidence_verification'
        and verification['data'].get('phase')=='baseline'
        and verification['data'].get('capture_id')==capture['id']
        and verification['data'].get('deterministic_id')==check['id']
        and verification['data'].get('status')in {'rejected','review_required'}
        and verification['data'].get('reason_code')in {'degraded','insufficient'}
        and check['data'].get('status')=='admitted' and not reasons)
    deterministic=(check['data'].get('status')=='rejected' and bool(reasons) and reasons.issubset(allowed))
    if (not (deterministic or visual) or
        capture['data'].get('source_preparation',{}).get('selection',{}).get('selected')!='network_response'):
        return capture,source,baseline,check
    ident=identity+'-rendered-context'
    try: alternative=store.get(ident+'-capture')
    except KeyError:
        data=capture['data'];rendered=store.read_blob(data['rendered_id']).decode()
        selected,preparation=prepare(source,rendered,data['captured_url'],replay_context_missing=True,animation_reference=data.get('visible',{}).get('animation_reference'),measurement_state=data.get('measurement_state'))
        blob=store.blob(selected,'verified_dynamic_context_candidate',campaign,'text/html')
        alternative=store.append('capture',{**data,'parent_capture_id':capture['id'],
            'replay_source_id':blob['id'],'source_preparation':preparation,
            'source_recovery':{'version':'verified-rendered-context-v7','original_capture_id':capture['id'],
               'original_audit_id':baseline['id'],'original_replay_id':check['id'],
               'reasons':sorted(reasons),'visual_verification_id':verification['id'] if visual else None,'maximum_alternatives':1}},campaign,ident+'-capture')
    selected=store.read_blob(alternative['data']['replay_source_id']).decode()
    try: audit=store.get(ident+'-audit')
    except KeyError: audit=environment.audit(alternative,selected,campaign,ident+'-audit',config)
    try: replay=store.get(ident+'-replay')
    except KeyError: replay=environment.replay_check(alternative,selected,campaign,ident+'-replay',audit)
    accepted=(audit['data'].get('status')=='completed' and replay['data'].get('status')=='admitted'
              and admission(selected,alternative['data'])['status']=='passed')
    try: store.get(ident+'-selection')
    except KeyError: store.append('source_selection',{'version':'verified-rendered-context-v7',
        'selected_capture_id':alternative['id'] if accepted else capture['id'],
        'alternative_capture_id':alternative['id'],'alternative_audit_id':audit['id'],
        'alternative_replay_id':replay['id'],'accepted':accepted,
        'stored_artifacts_modified':False,'paid_calls':0,'visual_verification_required':visual},campaign,ident+'-selection')
    return (alternative,selected,audit,replay) if accepted else (capture,source,baseline,check)
