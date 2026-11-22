"""Reuse A11yResearch's response/rendered source and proven widget adapters."""
from bs4 import BeautifulSoup
import hashlib
from remediation_content_contract import select_captured_patch_source,hydrate_static_placeholders,prepare_frozen_widget_replay
from .html_tools import absolutize_resources
from .capture_admission import challenge_kind


MEASUREMENT_STYLE = '*,*::before,*::after{animation-play-state:paused!important;transition-property:none!important;}'


def remove_measurement_style(rendered, network):
    """Omit only the known capture-injected pause rule absent from the response.

    A serialized paused rule would restart an already finished entrance effect
    at time zero. Replay applies its own freeze after normal resource settling.
    Authored, unknown and altered styles remain untouched.
    """
    marker = 'data-harness-measurement-freeze'
    original = BeautifulSoup(network, 'html.parser')
    if any(node.get(marker) == 'v3' and node.get_text() == MEASUREMENT_STYLE
           for node in original.find_all('style', attrs={marker: True})):
        return rendered, []
    soup = BeautifulSoup(rendered, 'html.parser')
    removed = []
    for node in soup.find_all('style', attrs={marker: 'v3'}):
        if node.get_text() != MEASUREMENT_STYLE:
            continue
        removed.append({'version': 'captured-measurement-style-omission-v1',
            'marker': 'v3', 'sha256': hashlib.sha256(str(node).encode()).hexdigest(),
            'reason': 'Capture-only pause rule must not restart finished CSS effects at time zero'})
        node.decompose()
    return (str(soup) if removed else rendered), removed


def prepare(network,rendered,base_url,replay_context_missing=False,animation_reference=None,measurement_state=None):
    challenge=challenge_kind(network)
    native=BeautifulSoup(rendered,'html.parser')
    if challenge and not challenge_kind(rendered) and native.body is not None and len(native.find_all(True))>=10:
        selected,selection=rendered,{'selected':'rendered_snapshot','reason':'Captured response is an earlier challenge; settled native DOM is user-facing','adapter':'settled-interstitial-v1','response_challenge':challenge}
    elif not network.strip() or BeautifulSoup(network,'html.parser').body is None:
        selected,selection=rendered,{'selected':'rendered_snapshot','reason':'Main document response is unavailable or not an HTML document'}
    else:selected,selection=select_captured_patch_source(network,rendered,base_url=base_url,replay_context_missing=replay_context_missing)
    selected,hydration=hydrate_static_placeholders(selected,rendered)
    selected,widgets=prepare_frozen_widget_replay(selected,captured_dom=(selection or {}).get('selected')=='rendered_snapshot')
    observed_animations=(measurement_state or {}).get('animations')
    restorable_effects=(isinstance(animation_reference,list)
        and (measurement_state or {}).get('version')=='frozen-measurement-state-v11'
        and type(observed_animations) is int and observed_animations==len(animation_reference)
        and all(isinstance(item,dict) and item.get('version')=='observed-css-animation-state-v1'
                and item.get('paused') is True for item in animation_reference))
    # Recorded active effects have their own exact restoration. A global pause
    # rule would also restart completed, unrecorded entrance effects at time zero.
    selected,measurement_styles=remove_measurement_style(selected,network) if (selection or {}).get('selected')=='rendered_snapshot' and restorable_effects else (selected,[])
    return absolutize_resources(selected,base_url),{'version':'a11yresearch-source-preparation-v8','measurement_styles_omitted':measurement_styles,'css_animation_reference_count':len(animation_reference) if isinstance(animation_reference,list) else None,'observed_animation_count':observed_animations,'selection':selection or {'selected':'network_response'},'static_media':hydration,'widgets':widgets,'stored_artifacts_modified':False}
