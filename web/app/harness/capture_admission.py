"""Conservative capture admission; this is not a semantic quality judgment."""
import re
from bs4 import BeautifulSoup

VERSION='capture-admission-v3'

def challenge_kind(source):
    """Explicit interstitial markers, not words in ordinary page content."""
    dom=BeautifulSoup(source,'html.parser')
    title=dom.title.get_text(' ',strip=True).casefold() if dom.title else ''
    if dom.select_one('script#anubis_challenge') and "not a bot" in title:
        return 'anubis_challenge'
    if title.strip().rstrip('.')=='just a moment' and (dom.select_one('#challenge-form') or '/cdn-cgi/challenge-platform/' in source):
        return 'cloudflare_challenge'
    return None


def assess(source,metadata):
    dom=BeautifulSoup(source,'html.parser')
    title=(dom.title.get_text(' ',strip=True) if dom.title else metadata.get('title','')).casefold()
    reasons=[];status=metadata.get('http_status')
    challenge=challenge_kind(source)
    if challenge:reasons.append(challenge)
    if isinstance(status,int) and status>=400:reasons.append('http_error')
    if 'sucuri' in title and 'access denied' in title:
        reasons.append('sucuri_access_block')
    if 'cloudflare' in title and ('attention required' in title or 'access denied' in title):
        reasons.append('cloudflare_access_block')
    if title.strip().rstrip('.')=='just a moment' and (dom.select_one('#challenge-form') or 'cf-chl-' in source or '/cdn-cgi/challenge-platform/' in source):
        if 'cloudflare_challenge' not in reasons:reasons.append('cloudflare_challenge')
    if re.search(r'\b(porn|pornography|hentai|xxx videos)\b',title):reasons.append('excluded_current_content')
    if title.strip() in ('domain for sale','buy this domain','parked domain','this domain is for sale'):reasons.append('parked_domain')
    if metadata.get('visible') is not None and (dom.body is None or len(dom.find_all(True))<5):reasons.append('no_user_facing_page')
    return {'version':VERSION,'status':'failed' if reasons else 'passed','reasons':reasons,
            'http_status':status,'title':metadata.get('title') or (dom.title.get_text(' ',strip=True) if dom.title else '')}
