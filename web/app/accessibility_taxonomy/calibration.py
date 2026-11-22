"""Declared instrument controls, never remediation or population study evidence."""
from .inventory import inventory

VERSION = 'taxonomy-calibration-controls-v3'
import hashlib

def controls(heldout=False):
    cases = [
        ('lang-mismatch','<html lang="en"><body>Welcome. Browse our products and contact our support team.</body></html>', '<html lang="fr"><body>Welcome. Browse our products and contact our support team.</body></html>', '<html lang="en"><body>123</body></html>'),
        ('language-of-parts-mismatch','<html lang="en"><body><p id="part" lang="es">Bienvenido. Consulta nuestros productos y contacta con nuestro equipo.</p></body></html>', '<html lang="en"><body><p id="part" lang="de">Bienvenido. Consulta nuestros productos y contacta con nuestro equipo.</p></body></html>', '<html lang="en"><body><p id="part" lang="es">123</p></body></html>'),
        ('page-title-not-descriptive','<html><head><title>Library opening hours</title></head><body><h1>Library opening hours</h1><p>The library opens Monday to Friday from nine to five.</p></body></html>', '<html><head><title>Banana recipe</title></head><body><h1>Library opening hours</h1><p>The library opens Monday to Friday from nine to five.</p></body></html>', '<html><head><title>Library opening hours</title></head><body></body></html>'),
        ('heading-not-descriptive','<html><body><section><h2 id="head">Shipping costs</h2><p>Standard shipping costs five dollars; express shipping costs ten dollars.</p></section></body></html>', '<html><body><section><h2 id="head">Password reset</h2><p>Standard shipping costs five dollars; express shipping costs ten dollars.</p></section></body></html>', '<html><body><h2 id="head">Shipping costs</h2></body></html>'),
        ('landmark-purpose-mismatch','<html><body><nav id="region" aria-label="Main navigation"><a href="/products">Products</a><a href="/contact">Contact</a></nav></body></html>', '<html><body><nav id="region" aria-label="Password reset form"><a href="/products">Products</a><a href="/contact">Contact</a></nav></body></html>', '<html><body><nav id="region" aria-label="Main navigation"></nav></body></html>'),
        ('form-label-mismatch','<html><body><form><label for="email">Email address</label><input id="email" type="email" name="email" placeholder="you@example.com"></form></body></html>', '<html><body><form><label for="email">Age in years</label><input id="email" type="email" name="email" placeholder="you@example.com"></form></body></html>', '<html><body><label for="field">Value</label><input id="field" type="text"></body></html>'),
        ('autocomplete-purpose-mismatch','<html><body><label for="email">Email address</label><input id="email" type="email" autocomplete="email" placeholder="you@example.com"></body></html>', '<html><body><label for="email">Email address</label><input id="email" type="email" autocomplete="postal-code" placeholder="you@example.com"></body></html>', '<html><body><input id="field" type="text" autocomplete="email"></body></html>'),
    ]
    if heldout:
        replacements={'Library opening hours':'Museum opening hours','library opens':'museum opens','Banana recipe':'Train departures','Shipping costs':'Delivery charges','shipping costs':'delivery costs','Password reset':'Account deletion','Products':'Collections','Contact':'Support','Main navigation':'Site navigation','Age in years':'Weight in kilograms','Email address':'Contact email','you@example.com':'contact@example.net','Value':'Data','Bienvenido. Consulta nuestros productos y contacta con nuestro equipo.':'Bienvenidos. Lee las noticias y consulta la información de nuestro servicio.'}
        cases=[(typ,*[__import__('functools').reduce(lambda text,pair:text.replace(*pair),replacements.items(),html) for html in (good,bad,unknown)]) for typ,good,bad,unknown in cases]
    bank=[]
    for typ,good,bad,unknown in cases:
        for status,html in [('passed',good),('failed',bad),('insufficient_evidence',unknown)]:
            row=next(r for r in inventory(html,{},'https://controls.invalid/')['opportunities'] if r['type']==typ)
            row['opportunity_id']='control-'+hashlib.sha256((typ+html).encode()).hexdigest()[:16]
            bank.append({'id':row['opportunity_id'],'expected':status,'html':html,'opportunity':row})
    for status,alt,visual in [('passed','A red square',True),('failed','A green circle',True),('insufficient_evidence','A red square',False)]:
        row=next(r for r in inventory('<img id="picture" src="square.png" alt="'+alt+'">',{},'https://controls.invalid/')['opportunities'] if r['type']=='image-alt-not-descriptive')
        row['opportunity_id']='control-'+hashlib.sha256((alt+str(visual)).encode()).hexdigest()[:16]
        if heldout:
            row['context']['element']['attributes']['alt']=alt.replace('red','blue').replace('green','yellow')
            row['opportunity_id']='heldout-'+row['opportunity_id']
        if visual:row['method']='decisions';row['context']['supplementary_image']={'description':'Verified image attached as image 1, paired with this element.'}
        bank.append({'id':row['opportunity_id'],'expected':status,'opportunity':row,'image':visual})
    return bank

def score(bank, replicas):
    ids=[r['id'] for r in bank]; expected={r['id']:r['expected'] for r in bank}
    records=[{'id':ident,'expected':expected[ident],'observed':[r.get(ident,'error') for r in replicas]} for ident in ids]
    total=len(records)*len(replicas)
    correct=sum(v==r['expected'] for r in records for v in r['observed'])
    disagreements=sum(len(set(r['observed']))>1 for r in records)
    failures=[r for r in records if any(v!=r['expected'] for v in r['observed'])]
    return {'version':VERSION,'questions':total,'correct':correct,'disagreements':disagreements,'failures':failures,'records':records,
            'gate_passed':len(replicas)==2 and not failures and not disagreements,
            'scope':'Constructed controls only; no population accuracy or human agreement claim.'}

RELATIONAL_VERSION = 'taxonomy-relational-controls-v2'
def relational_controls(heldout=False):
    """Independent configured-purpose/state controls; no task-success claim."""
    cases=[
      ('link-text-mismatch','<a href="#contact">Contact our team</a><section id="contact"><h2>Contact our team</h2><p>Email support@example.org for help.</p></section>', '<a href="#contact">Shipping prices</a><section id="contact"><h2>Contact our team</h2><p>Email support@example.org for help.</p></section>', '<a href="javascript:void(0)">Continue</a>'),
      ('button-label-mismatch','<form><label for="email">Email</label><input id="email" type="email"><button type="reset">Clear this form</button></form>', '<form><label for="email">Email</label><input id="email" type="email"><button type="reset">Send payment</button></form>', '<button type="button" onclick="opaqueHandler()">Continue</button>'),
      ('widget-label-purpose-mismatch','<div role="tab" aria-label="Shipping" aria-controls="panel">Shipping</div><section id="panel"><h2>Shipping</h2><p>Delivery costs and shipping times.</p></section>', '<div role="tab" aria-label="Change password" aria-controls="panel">Change password</div><section id="panel"><h2>Shipping</h2><p>Delivery costs and shipping times.</p></section>', '<div role="tab" aria-label="Continue">Continue</div>'),
      ('aria-state-mismatch','<input type="checkbox" aria-label="Subscribe" aria-checked="false">', '<input type="checkbox" aria-label="Subscribe" aria-checked="true">', '<div role="button" aria-label="Toggle" aria-pressed="true">Toggle</div>'),
      ('table-header-association-mismatch','<table><caption>Product measurements</caption><tr><th id="price" scope="col">Price</th><th id="weight" scope="col">Weight</th></tr><tr><td headers="price">10 USD</td><td>5 kg</td></tr></table>', '<table><caption>Product measurements</caption><tr><th id="price" scope="col">Price</th><th id="weight" scope="col">Weight</th></tr><tr><td headers="weight">10 USD</td><td>5 kg</td></tr></table>', '<table><tr><td headers="missing">10 USD</td></tr></table>'),
      ('error-message-mismatch','<label for="email">Email address</label><input id="email" type="email" required aria-errormessage="err"><p id="err">Enter your email address.</p>', '<label for="email">Email address</label><input id="email" type="email" required aria-errormessage="err"><p id="err">Age must be over 18.</p>', '<label for="value">Value</label><input id="value" aria-errormessage="err"><p id="err">Check this value.</p>')]
    if heldout:
        substitutions={'Contact our team':'Customer support','Shipping prices':'Password reset','support@example.org':'help@example.net','Shipping':'Delivery','Change password':'Account security','Email address':'Contact email','Price':'Cost','Weight':'Mass','10 USD':'25 EUR','5 kg':'3 kg','18':'21'}
        cases=[(typ,*[__import__('functools').reduce(lambda text,pair:text.replace(*pair),substitutions.items(),html) for html in group]) for typ,*group in cases]
    bank=[]
    for typ,*group in cases:
        for status,body in zip(('passed','failed','not_applicable' if typ=='table-header-association-mismatch' else 'insufficient_evidence'),group):
            html='<html><head></head><body>'+body+'</body></html>'
            ident='relational-'+hashlib.sha256((typ+html).encode()).hexdigest()[:20]
            bank.append({'id':ident,'type':typ,'expected':status,'html':html,'target_tag':'td' if typ=='table-header-association-mismatch' else None})
    good_table=next(x['html'] for x in bank if x['type']=='table-header-association-mismatch' and x['expected']=='passed')
    for header in ('price','weight'):
        ident='relational-header-'+hashlib.sha256((good_table+header).encode()).hexdigest()[:20]
        bank.append({'id':ident,'type':'table-header-association-mismatch','expected':'passed','html':good_table,'target_id':header})
    return bank
