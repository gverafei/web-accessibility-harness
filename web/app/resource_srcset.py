"""Preserve commas inside URL tokens when processing HTML srcset candidates."""
def candidates(value):
    index=0;length=len(value)
    while index<length:
        while index<length and (value[index].isspace() or value[index]==','):index+=1
        start=index
        while index<length and not value[index].isspace():index+=1
        url=value[start:index]
        if not url:break
        if url.endswith(','):
            yield url.rstrip(','),''
            continue
        while index<length and value[index].isspace():index+=1
        start=index;depth=0
        while index<length:
            char=value[index]
            if char=='(':depth+=1
            elif char==')':depth=max(0,depth-1)
            elif char==',' and depth==0:break
            index+=1
        yield url,value[start:index].strip()
        index+=1

def rewrite(value,resolve):
    if 'data:' in value.lower():return value
    return ', '.join((resolve(url)+' '+descriptor).rstrip() for url,descriptor in candidates(value))
