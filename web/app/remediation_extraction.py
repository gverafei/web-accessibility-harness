import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
"""Frozen-source acquisition QA and task-aware intermediate representations."""
import os
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin




def local_markdown(source, base_url):
    soup=BeautifulSoup(source,"html.parser")
    for form in soup.select('form'):
        controls=[]
        for control in form.select('input[name],select[name],textarea[name],button[name]'):
            controls.append(f"- Field `{control['name']}`: {control.get('type',control.name)}; value `{control.get('value','')}`.")
        form.append('\n\nForm contract (acquired source):\n'
                    +f"- Method: {form.get('method','get').upper()}; action: {urljoin(base_url,form.get('action',''))}\n"
                    +'\n'.join(controls)+'\n')
    for node in soup.select("script,style,noscript,template"): node.decompose()
    for node in soup.select("img"):
        node.replace_with(f" ![{node.get('alt') or ''}]({urljoin(base_url,node.get('src') or node.get('data-src') or '')}) ")
    for node in soup.select("a[href]"):
        node.replace_with(f" [{node.get_text(' ',strip=True)}]({urljoin(base_url,node.get('href'))}) ")
    for node in soup.select("h1,h2,h3,h4,h5,h6"):
        node.insert_before("\n"+"#"*int(node.name[1])); node.insert_after("\n")
    for node in soup.select("p,li,section,article,nav,header,footer,tr"):
        node.insert_before("\n"); node.insert_after("\n")
    return re.sub(r"\n{3,}","\n\n",soup.get_text(" ")).strip()


def markdown_quality(source, markdown, base_url):
    """Check source-owned text and media without importing the old layout."""
    soup=BeautifulSoup(source,'html.parser')
    # Match the content boundary used by local_markdown. Tracking pixels in
    # noscript/head are not part of the preserved reading-order representation.
    for node in soup.select('script,style,noscript,template,head'): node.decompose()
    images={urljoin(base_url,img.get('src') or img.get('data-src') or '') for img in soup.select('img')}
    links={urljoin(base_url,a['href']) for a in soup.select('a[href]')}
    words=set(re.findall(r'\w+',soup.get_text(' ',strip=True).casefold()))
    retained=set(re.findall(r'\w+',markdown.casefold()))
    return {'missing_images':sorted(url for url in images if url not in markdown),
            'missing_links':sorted(url for url in links if url not in markdown),
            'text_vocabulary_retained_percent':round(100*len(words&retained)/max(1,len(words)),2)}


def extraction_quality(network_html, rendered_html):
    def inspect(source):
        soup=BeautifulSoup(source,"html.parser")
        for node in soup.select("script,style,noscript,template"): node.decompose()
        return {"words":len(soup.get_text(" ",strip=True).split()),"links":len(soup.select("a[href]")),"images":len(soup.select("img")),"forms":len(soup.select("form")),"iframes":len(soup.select("iframe"))}
    network, rendered=inspect(network_html),inspect(rendered_html)
    warnings=[]
    if rendered["words"] < network["words"]*.8: warnings.append("Rendered document has substantially less text than network source; retain both views")
    if rendered["iframes"]: warnings.append("Embedded documents require separate acquisition; main-document extraction is not complete for iframe tasks")
    if re.search(r"<title>\s*(error response|access denied|just a moment)",rendered_html,re.I): warnings.append("Possible error/challenge snapshot")
    return {"network":network,"rendered":rendered,"warnings":warnings,"method":"frozen network source + browser-rendered DOM; no silent re-acquisition"}

def markdown_representation(source, base_url, provider="local"):
    """Jina receives the frozen HTML, not a new live URL crawl."""
    if provider not in {"local","jina"}: raise ValueError("Unsupported Markdown adapter")
    warnings=[]
    if provider=="jina":
        headers={"x-respond-with":"markdown","x-retain-images":"all","x-retain-links":"all"}
        if os.getenv("JINA_API_KEY"): headers["Authorization"]="Bearer "+os.environ["JINA_API_KEY"]
        try:
            response=requests.post("https://r.jina.ai/",json={"html":source,"url":base_url},headers=headers,timeout=45)
            response.raise_for_status(); markdown=response.text
            if not markdown.strip(): raise ValueError("Jina returned an empty representation")
        except (requests.RequestException,ValueError) as error:
            warnings.append("Jina unavailable; used frozen local Markdown: "+type(error).__name__)
            provider="local"; markdown=local_markdown(source,base_url)
    else: markdown=local_markdown(source,base_url)
    # Markdown is NEVER the sole source for controls/actions or omitted assets.
    return {"provider":provider,"markdown":markdown,"warnings":warnings,"task_contract":"Full HTML/inventory remains authoritative for forms, controls, resources and destinations"}
