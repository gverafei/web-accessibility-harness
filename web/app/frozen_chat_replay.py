"""Recognized Oracle chat construction guard; captured markup remains unchanged."""
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

VERSION = 'oracle-chat-frozen-replay-v3'
RUNTIME = Path(__file__).with_suffix('.js')
ROOTS = '.ochat_slideout[data-trackas="ochat_slideout"], #ochat_modal.ochat_modal[data-trackas="ochat-modal"]'


def prepare_chat(soup):
    loaders = soup.select('script#oracle_chat[src]')
    if len(loaders) != 1:
        return []
    url = urlsplit(loaders[0]['src'])
    if url.hostname != 'www.oracle.com' or url.path != '/asset/web/js/oracle-chat.js':
        return []
    roots = soup.select(ROOTS)
    if (len(roots) != 2 or len(soup.select('#ochat_modal')) != 1
            or len(soup.select('.ochat_slideout')) != 1
            or not soup.select_one('.ochat_slideout .ochat_slidew2 .ochat_flyout')
            or not soup.select_one('#ochat_modal .ochat_modalw1 .ochat_modalw2')):
        return []  # Unknown/incomplete SDK versions are diagnostic, never generic deduplication.
    if soup.select('script[data-warp-frozen-chat-runtime]'):
        return []
    if not loaders[0].find_parent('body'):
        return []
    # Generated roots occur after the authored loader in serialized snapshots.
    # Place those same nodes before it, so the guard can see them during parsing;
    # otherwise the loader constructs its roots before the captured ones exist.
    reactive = soup.select('#oReactiveChatContainer.rn_ConditionalChatLink')
    frozen_roots = [*roots, *reactive] if len(reactive) == 1 else roots
    for root in frozen_roots:
        loaders[0].insert_before(root.extract())
    runtime = RUNTIME.read_text(encoding='utf-8')
    script = soup.new_tag('script')
    script['data-warp-frozen-chat-runtime'] = VERSION
    script.string = runtime
    loaders[0].insert_before(script)
    return [{'component': 'oracle-chat', 'version': VERSION,
             'runtime_sha256': hashlib.sha256(runtime.encode()).hexdigest(),
             'method': 'place unchanged captured SDK roots before loader; suppress repeated jQuery construction; preserve event binding',
             'limitations': 'construction replay only; remote chat transaction and task equivalence unverified'}]
