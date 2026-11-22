"""Index safe selector anchors; SoupSieve still performs the exact CSS match."""
import re
from collections import defaultdict
import soupsieve

class SelectorIndex:
    def __init__(self,soup):
        self.soup=soup;self.cache={};self.attributes=defaultdict(list);self.classes=defaultdict(list);self.tags=defaultdict(list)
        for node in soup.find_all(True):
            self.tags[node.name].append(node)
            for name,value in node.attrs.items():
                if isinstance(value,list):value=' '.join(value)
                if isinstance(value,str):self.attributes[(name,value)].append(node)
            for value in node.get('class',[]):self.classes[value].append(node)

    def select(self,selector):
        if selector in self.cache:return self.cache[selector]
        anchors=None;end=0
        # Escapes, selector lists and sibling combinators use the full engine.
        # The indexed anchor must be the first compound: every possible match
        # is that node or its descendant, so uniqueness is still checked.
        if not any(token in selector for token in ('\\',',','+','~')):
            attribute=re.match(r'^([A-Za-z][\w-]*)\[([A-Za-z][\w-]*)="([^"\\]*)"\]',selector)
            simple=re.match(r'^([.#])([A-Za-z_][\w-]*)(?=$|[\s>\[.:#])',selector)
            tag=re.fullmatch(r'[A-Za-z][\w-]*',selector)
            if attribute:
                anchors=[n for n in self.attributes[(attribute[2].lower(),attribute[3])] if n.name==attribute[1].lower()];end=attribute.end()
            elif simple:
                anchors=self.classes[simple[2]] if simple[1]=='.' else self.attributes[('id',simple[2])];end=simple.end()
            elif tag:anchors=self.tags[selector.lower()];end=len(selector)
        if anchors is None:result=self.soup.select(selector)
        else:
            compiled=soupsieve.compile(selector);result=[];seen=set()
            for anchor in anchors:
                candidates=[anchor] if end==len(selector) else [anchor,*anchor.find_all(True)]
                for node in candidates:
                    if id(node) not in seen and compiled.match(node):result.append(node);seen.add(id(node))
        self.cache[selector]=result
        return result
