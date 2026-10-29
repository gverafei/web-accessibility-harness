"""Acquisition and common frozen local replay, with original URLs kept in evidence."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import requests
from bs4 import BeautifulSoup
from .contracts import ContractError, canonical, digest, SCHEMA

class EnvironmentChanged(RuntimeError):
    pass

class Environment:
    def __init__(self, store, session=requests, evaluator=None, datasets=None, results=None):
        self.store, self.session = store, session
        self.evaluator = evaluator or os.getenv('EVALUATOR_URL', 'http://evaluator:3000')
        self.datasets = Path(datasets or os.getenv('HARNESS_REPLAY_ROOT', '/datasets/harness'))
        self.results = Path(results or '/results').resolve()

    def post(self, endpoint, body, timeout=240):
        response = self.session.post(self.evaluator.rstrip('/') + endpoint, json=body, timeout=timeout)
        if response.status_code>=400:
            payload=response.json()
            failure=ContractError('Evaluator '+endpoint+' HTTP '+str(response.status_code)+': '+str(payload.get('error','unavailable'))[:2000])
            failure.evaluator_details={'endpoint':endpoint,'http_status':response.status_code,**payload}
            raise failure
        return response.json()

    def post_snapshot(self, body, campaign, ident, source):
        """Retry a crashed local browser once, with the identical document."""
        # A condition slot bounds generative work. Browser audits share a
        # separate host-capacity lock so concurrent large pages cannot starve
        # one another inside their unchanged per-audit deadline.
        with self.store.named_lock('original-origin-browser-capacity-v1'):
            return self._post_snapshot_owned(body, campaign, ident, source)

    def _post_snapshot_owned(self, body, campaign, ident, source):
        for attempt in range(2):
            try:
                return self.post('/harness/origin-snapshot', body)
            except ContractError as error:
                transient = any(signal in str(error) for signal in (
                    'Target crashed', 'browser disconnected', 'Browser closed unexpectedly'))
                if attempt or not transient:
                    raise
                self.store.append('instrument_retry', {
                    'operation': 'origin-snapshot', 'audit_id': ident, 'reason': str(error),
                    'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
                    'retry': 1, 'generation_repeated': False,
                }, campaign)

    def file(self, value):
        path = Path(value).resolve()
        if not path.is_relative_to(self.results):
            raise ContractError('Evaluator artifact is outside the results mount')
        return path.read_bytes()

    def runtime(self):
        response=self.session.get(self.evaluator.rstrip('/')+'/health',timeout=15)
        response.raise_for_status()
        runtime=response.json().get('runtime')
        if not isinstance(runtime,dict) or not runtime.get('source_files'):
            raise EnvironmentChanged('Evaluator runtime provenance is unavailable')
        return runtime

    def verify_runtime(self,campaign):
        current=self.runtime();ident=campaign+'-evaluator-runtime'
        revision = getattr(self, 'evaluator_revision_id', None)
        if revision:
            from .evaluator_recovery import validate
            validate(self.store, campaign, revision, current)
            return
        try: expected=self.store.get(ident)['data']
        except KeyError:
            self.store.append('evaluator_snapshot',current,campaign,ident);return
        if expected!={'schema':SCHEMA, **current}:
            raise EnvironmentChanged('Evaluator code/tool versions changed after the campaign runtime was frozen')

    def binding_runtime(self, campaign):
        current = self.runtime()
        revision = getattr(self, 'evaluator_revision_id', None)
        if revision:
            from .evaluator_recovery import validate
            return validate(self.store, campaign, revision, current)
        return current

    def capture_request(self,endpoint,url,campaign,ident,payload=None):
        try:
            return self.post(endpoint,payload if payload is not None else {'url':url},300)
        except (ContractError,requests.RequestException) as error:
            self.store.append('acquisition_failure',{'url':url,'attempt':ident,'error':str(error),
                'details':getattr(error,'evaluator_details',None),
                'scope':'Technical acquisition/reproduction failure before LLM verification; no automatic content rejection.'},campaign)
            raise

    def capture(self, url, campaign, ident):
        response = self.capture_request('/harness/capture',url,campaign,ident)
        return self.store_capture(response, campaign, ident)

    def capture_verified(self, url, campaign, ident, config=None):
        """Reuse the main native acquisition and its frozen resource package."""
        response = self.capture_request('/evaluate', url, campaign, ident, {
            'experiment_id': ident, 'urls': [url], 'include_wave': False,
            'axe_standard': (config or {}).get('axe_standard', 'wcag22aa'),
            'quality_policy': {'require_complete_evidence': True, 'exclude_explicit_content': True},
        })
        items = response.get('results', [])
        if len(items) != 1 or items[0].get('status') != 'completed':
            raise ContractError('Native acquisition failed: ' + str(items[0].get('error') if items else 'missing result'))
        item = items[0]
        package = item['screenshot_path'] + '.resources.json'
        raw_package = self.file(package)
        metadata = json.loads(raw_package)
        if metadata.get('version') not in ('native-resource-package-v1', 'native-resource-package-v2',
                                            'native-resource-package-v3', 'native-resource-package-v4'):
            raise ContractError('Native acquisition package version is unavailable')
        if (metadata.get('requested_url') != url
                or metadata.get('network', '').encode() != self.file(item['response_source_path'])
                or metadata.get('rendered', '').encode() != self.file(item['source_snapshot_path'])):
            raise ContractError('Native acquisition document/package identity mismatch')
        transport = self.store_capture({'capture_path': package,
            'screenshot_path': item['screenshot_path']}, campaign, ident + '-native-package')
        artifacts = {key: self.store.blob(self.file(item[key]['raw_path']), key + '_audit',
                     campaign, 'application/json')['id'] for key in ('axe', 'lighthouse')}
        measurement = self.store.append('acquisition_measurement', {
            'capture_id': transport['id'], 'artifacts': artifacts,
            'axe': item['axe']['wcag_violations'], 'lighthouse': item['lighthouse']['accessibility_score'],
            'scope': 'Native same-document acquisition measurements; prepared-input reference is measured separately',
        }, campaign, ident + '-native-measurement')
        return self.store.append('capture', {**transport['data'],
            'parent_capture_id': transport['id'], 'resource_acquisition': 'native-acquisition-package',
            'package_sha256': hashlib.sha256(raw_package).hexdigest(),
            'acquisition_measurement_id': measurement['id']}, campaign, ident)

    def freeze_source(self, url, origin, source, rendered, screenshot, campaign, ident):
        """Freeze stored acquisition resources without replacing its original evidence."""
        package=Path(screenshot+'.resources.json')
        if package.is_file():
            payload=json.loads(self.file(package))
            if payload.get('version') not in ('native-resource-package-v1','native-resource-package-v2','native-resource-package-v3','native-resource-package-v4') or payload.get('captured_url')!=origin:
                raise ContractError('Native resource package origin/version mismatch')
            record=self.store_capture({'capture_path':str(package),'screenshot_path':screenshot},campaign,ident+'-transport')
            provenance={'resource_acquisition':'native-acquisition-package','package_sha256':hashlib.sha256(self.file(package)).hexdigest()}
        else:
            # Legacy acquisition has no frozen package: explicit native resource
            # recovery, never replace the captured model input or old evidence.
            recovery_key='native-resource-recovery-'+digest({'version':'native-resource-package-v1',
                'origin':origin,'source_sha256':hashlib.sha256(source.encode() if isinstance(source,str) else source).hexdigest(),
                'rendered_sha256':hashlib.sha256(rendered.encode() if isinstance(rendered,str) else rendered).hexdigest(),
                'screenshot':hashlib.sha256(Path(screenshot).read_bytes()).hexdigest() if Path(screenshot).is_file() else None})
            try:
                record=self.store.get(recovery_key)
            except KeyError:
                record=self.capture(origin,campaign,recovery_key)
            if record['kind']!='capture' or record['data']['captured_url']!=origin:
                raise ContractError('Frozen recovery identity mismatch')
            for asset in record['data'].get('assets',[]):
                try:self.store.read_blob(asset['artifact_id'])
                except (KeyError,FileNotFoundError) as error:
                    raise ContractError('Frozen recovery resource is unavailable; explicit recovery required') from error
            provenance={'resource_acquisition':'recorded-legacy-native-recovery','recovery_capture_id':record['id'],
                        'stored_source_replaced':False}
        data = dict(record['data'])
        data.update(provenance)
        data.update(requested_url=origin,captured_url=origin,
            network_id=self.store.blob(source,'acquired_source_html',campaign,'text/html')['id'],
            rendered_id=self.store.blob(rendered,'acquired_rendered_html',campaign,'text/html')['id'],
            replay_source_id=self.store.blob(source,'replay_source_html',campaign,'text/html')['id'],
            screenshot_id=self.store.blob(Path(screenshot).read_bytes(),'acquired_screenshot',campaign,'image/jpeg')['id'],
            visible_source='native acquisition reference; model HTML preserved separately',
            parent_capture_id=record['id'])
        return self.store.append('capture', data, campaign, ident)

    def store_capture(self, response, campaign, ident):
        capture = json.loads(self.file(response['capture_path']))
        network = self.store.blob(capture.pop('network'), 'network_html', campaign, 'text/html')
        rendered = self.store.blob(capture.pop('rendered'), 'rendered_html', campaign, 'text/html')
        from .source_preparation import prepare
        source,preparation=prepare(self.store.read_blob(network['id']).decode(),self.store.read_blob(rendered['id']).decode(),capture['captured_url'],animation_reference=capture.get('visible',{}).get('animation_reference'),measurement_state=capture.get('measurement_state'))
        replay_source=self.store.blob(source,'replay_source_html',campaign,'text/html')
        screenshot = self.store.blob(self.file(response['screenshot_path']), 'capture_screenshot', campaign, 'image/jpeg')
        segment_path=Path(response['screenshot_path']+'.segments.json')
        segments=[]
        if segment_path.is_file():
            descriptor=json.loads(self.file(segment_path))
            for item in descriptor['segments']:
                artifact=self.store.blob(self.file(item['path']),'desktop_segment',campaign,'image/jpeg')
                segments.append({k:v for k,v in item.items() if k!='path'}|{'artifact_id':artifact['id']})
            capture['screenshot_segments']={'version':descriptor['version'],'complete':descriptor['complete'],'segments':segments}
        mse=capture.get('mse_buffer_reference')
        if mse:
            for record in mse.get('records',[]):
                for buffer in record.get('buffers',[]):
                    for item in buffer.get('appends',[]):
                        raw=base64.b64decode(item.pop('body'),validate=True)
                        if hashlib.sha256(raw).hexdigest()!=item['sha256'] or len(raw)!=item['byte_length']:
                            raise ContractError('Derived MSE buffer checksum mismatch')
                        item['artifact_id']=self.store.blob(raw,'observed_mse_append',campaign,'application/octet-stream')['id']
        worker=capture.get('worker_media_reference')
        if worker:
            for record in worker.get('records',[]):
                for item in record.get('buffers',[]):
                    raw=base64.b64decode(item.pop('body'),validate=True)
                    if hashlib.sha256(raw).hexdigest()!=item['sha256'] or len(raw)!=item['byte_length']:
                        raise ContractError('Derived worker media checksum mismatch')
                    item['artifact_id']=self.store.blob(raw,'observed_worker_media_init',campaign,'application/octet-stream')['id']
        assets = []
        for item in capture.pop('assets'):
            raw = base64.b64decode(item['body'], validate=True)
            if hashlib.sha256(raw).hexdigest() != item['sha256']:
                raise ContractError('Captured resource checksum mismatch')
            blob = self.store.blob(raw, 'captured_resource', campaign, item['mime'])
            assets.append({k:v for k,v in item.items() if k != 'body'} | {'artifact_id':blob['id']})
        return self.store.append('capture', {**capture, 'network_id':network['id'], 'rendered_id':rendered['id'],
                                 'replay_source_id':replay_source['id'],'source_preparation':preparation,
                                 'screenshot_id':screenshot['id'], 'assets':assets}, campaign, ident)

    def with_design_resources(self,capture,campaign):
        # Historical caller compatibility: never fetch or impose design dependencies.
        return capture

    def replay(self, capture, source, ident, base_url=None):
        data = capture['data']; root = self.datasets / capture['id']; root.mkdir(parents=True, exist_ok=True)
        base = base_url or 'http://dataset-server:8080/harness/' + capture['id'] + '/'
        mapping = {a['url']:base + 'assets/' + a['sha256'] for a in data['assets']}
        assets_dir = root / 'assets'; assets_dir.mkdir(exist_ok=True)
        missing = set()
        def resource(value, origin):
            if value.startswith(('data:', 'blob:', '#')): return value
            url = urljoin(origin, value)
            if url in mapping: return mapping[url]
            missing.add(url); return base + 'uncaptured/' + hashlib.sha256(url.encode()).hexdigest()
        (assets_dir / '.content-types.json').write_text(canonical({a['sha256']:a['mime'].split(';')[0] for a in data['assets']}),encoding='utf-8')
        for asset in data['assets']:
            raw = self.store.read_blob(asset['artifact_id'])
            if 'text/css' in asset['mime']:
                css = raw.decode('utf-8', errors='replace')
                css = re.sub(r'url\(\s*[\'"]?([^\)\'"\s]+)[\'"]?\s*\)', lambda m:'url("'+resource(m[1],asset['url'])+'")', css)
                css = re.sub(r'@import\s+[\'"]([^\'"]+)[\'"]', lambda m:'@import "'+resource(m[1],asset['url'])+'"',css)
                raw = css.encode()
            (assets_dir / asset['sha256']).write_bytes(raw)
        soup = BeautifulSoup(source, 'html.parser')
        transport_changes=[]
        for node in soup.select('base,meta[http-equiv="refresh"]'): node.decompose()
        for node in soup.find_all(True):
            for attr in ('src','poster','data-src','data-original'):
                if node.has_attr(attr): node[attr] = resource(node[attr], data['captured_url'])
            if node.name=='a' and node.has_attr('href') and not node['href'].startswith(('#','mailto:','tel:','javascript:')):node['href']=urljoin(data['captured_url'],node['href'])
            if node.name=='form' and node.has_attr('action'):node['action']=urljoin(data['captured_url'],node['action'])
            if node.name == 'link' and node.has_attr('href'):
                node['href'] = resource(node['href'], data['captured_url'])
                # CSS URL rewriting changes transport bytes; the original SRI stays in the immutable source.
                if node['href'].startswith(base) and node.has_attr('integrity'):
                    transport_changes.append({'element':'link','resource':node['href'],'change':'SRI removed from local transport after CSS URL rewriting; immutable source retains original integrity'})
                    node.attrs.pop('integrity',None)
            for attr in ('srcset','data-srcset'):
                if node.has_attr(attr) and 'data:' not in node[attr].lower():
                    from resource_srcset import rewrite
                    node[attr] = rewrite(node[attr],lambda value:resource(value,data['captured_url']))
            if node.has_attr('style'):
                node['style'] = re.sub(r'url\([\'"]?([^\)\'"]+)[\'"]?\)', lambda m:'url("'+resource(m[1],data['captured_url'])+'")',node['style'])
        for node in soup.find_all('style'):
            node.string = re.sub(r'url\([\'"]?([^\)\'"]+)[\'"]?\)', lambda m:'url("'+resource(m[1],data['captured_url'])+'")',node.get_text())
        path = root / (ident + '.html'); path.write_text(str(soup),encoding='utf-8')
        return base + path.name, {'resource_map':mapping, 'uncaptured':sorted(missing),
                                 'transport_changes':transport_changes,'scope':data['scope']}

    def origin_manifest(self, capture, source, campaign, ident, config):
        version='original-origin-injection-v2'
        from remediation_content_contract import prepare_frozen_widget_replay
        rendered_document, widget_adapters = prepare_frozen_widget_replay(source)
        assets=[]
        # Explicit recorded-entry precedence; preserve all capture blobs and discarded hashes.
        selected={};duplicates=[];media_fragments={};resource_records={}
        for asset in capture['data']['assets']:
            resource_records.setdefault(asset['url'],[]).append(asset)
            if asset['mime'].split(';')[0].startswith(('video/','audio/')):
                media_fragments.setdefault(asset['url'],[]).append(asset)
            if asset['url'] in selected:
                duplicates.append({'url':asset['url'],'previous_sha256':selected[asset['url']]['sha256'],'selected_sha256':asset['sha256']})
            selected[asset['url']]=asset
        # Freeze the latest browser-observed HLS entity at this capture's
        # cutoff. Response ordinals precede asynchronous body completion.
        # Earlier native redirect routes still reach this frozen endpoint;
        # changed permissions or recovery-only bodies never inherit them.
        hls_choices=[];sequenced_hls=set()
        for url,records in resource_records.items():
            native=[r for r in records if r['mime'].split(';')[0].strip().lower() in
                    ('application/vnd.apple.mpegurl','application/x-mpegurl','audio/mpegurl','audio/x-mpegurl')
                    and r.get('http_status',200)==200 and type(r.get('native_response_sequence')) is int
                    and r['native_response_sequence']>0 and r.get('body_representation',{}).get('kind') in
                    ('browser_response_entity','decoded_complete_entity')]
            if not native:continue
            if len({r['native_response_sequence'] for r in native})!=len(native):
                raise ContractError('Ambiguous native response sequence')
            chosen=max(native,key=lambda r:r['native_response_sequence'])
            if not self.store.read_blob(chosen['artifact_id']).startswith((b'#EXTM3U\n',b'#EXTM3U\r\n')):
                raise ContractError('Native HLS entity lacks playlist signature')
            original=selected[url];selected[url]=chosen;sequenced_hls.add(url)
            hls_choices.append({'url':url,'selected_sha256':chosen['sha256'],'previous_sha256':original['sha256'],
                                'native_response_sequence':chosen['native_response_sequence'],
                                'scope':'Latest complete browser-observed playlist entity at capture cutoff'})
        # The injected document is supplied separately. Earlier navigation responses
        # (including protection pages) are acquisition evidence, not simultaneous
        # subresources. Keep their blobs and record this exclusion explicitly.
        origin=capture['data']['captured_url']
        navigation_urls={origin}
        for asset in selected.values():
            if asset['url']==origin and asset['mime'].split(';')[0].strip().lower()=='text/html':
                navigation_urls.update(r['from'] for r in asset.get('redirect_chain',[]))
        navigation=[]; ephemeral=[];unsupported=[]
        for asset in selected.values():
            if urlsplit(asset['url']).scheme not in ('http','https'):
                ephemeral.append({'url':asset['url'],'sha256':asset['sha256'],'reason':'Opaque browser-local resource is acquisition evidence, not an HTTP network response'})
                continue
            if asset['url'] in navigation_urls and asset['mime'].split(';')[0].strip().lower()=='text/html':
                navigation.append({'url':asset['url'],'sha256':asset['sha256'],'reason':'document supplied by injection'})
                continue
            variants=media_fragments.get(asset['url'],[asset])
            stylesheet=asset['mime'].split(';')[0].strip().lower()=='text/css'
            if stylesheet:
                # Preserve complete observed header variants only for the selected CSS bytes.
                variants=[record for record in resource_records[asset['url']]
                          if record['sha256']==asset['sha256'] and record['mime']==asset['mime']
                          and record.get('http_status',200)==asset.get('http_status',200)]
            seen=set()
            for variant in variants:
                if variant.get('body_representation',{}).get('kind')=='unsupported_encoded_range':
                    unsupported.append({'url':variant['url'],'sha256':variant['sha256'],'body_representation':variant['body_representation'],'reason':'Captured decoded partial body has no verified logical offsets'})
                    continue
                identity=(variant['sha256'],variant.get('http_status',200),variant.get('headers',{}).get('content-range'),
                          canonical(variant.get('headers',{})) if stylesheet else None)
                if identity in seen: continue
                seen.add(identity)
                chains=[]
                primary=variant.get('redirect_chain',[])
                for recorded in resource_records[variant['url']]:
                    if ((recorded['sha256']==variant['sha256'] or (variant['url'] in sequenced_hls
                            and type(recorded.get('native_response_sequence')) is int
                            and 0<recorded['native_response_sequence']<=variant['native_response_sequence']
                            and recorded.get('body_representation',{}).get('kind') in ('browser_response_entity','decoded_complete_entity')))
                            and recorded['mime']==variant['mime']
                            and recorded.get('http_status',200)==variant.get('http_status',200)
                            and recorded.get('headers',{})==variant.get('headers',{})):
                        chain=recorded.get('redirect_chain',[])
                        if chain and chain!=primary and chain not in chains:chains.append(chain)
                if len(chains)>64:raise ContractError('Recorded redirect alias chain limit exceeded')
                assets.append({k:variant[k] for k in ('url','mime','sha256')} | {
                    'http_status':variant.get('http_status',200),'headers':variant.get('headers',{}),
                    'redirect_chain':primary,'additional_redirect_chains':chains,
                    **({'body_representation':variant['body_representation']} if variant.get('body_representation') else {}),
                    **({'native_response_sequence':variant['native_response_sequence']} if variant.get('native_response_sequence') else {}),
                    'body':base64.b64encode(self.store.read_blob(variant['artifact_id'])).decode()})
        payload={'version':version,'origin':capture['data']['captured_url'],
                 'document':rendered_document,'assets':assets,'standard':config.get('axe_standard','wcag22aa'),
                 'preflights':capture['data'].get('preflights',[]),
                 'media_reference':capture['data'].get('visible',{}).get('media_descriptors',[]),
                 'animation_reference':capture['data'].get('visible',{}).get('animation_reference',[])}
        if capture['data'].get('native_control_reference') is not None:
            payload['native_control_reference']=capture['data']['native_control_reference']
        mse=capture['data'].get('mse_buffer_reference')
        derived_bytes=0
        if mse:
            mse=json.loads(json.dumps(mse))
            for record in mse.get('records',[]):
                for buffer in record.get('buffers',[]):
                    for item in buffer.get('appends',[]):
                        raw=self.store.read_blob(item['artifact_id'])
                        derived_bytes+=len(raw)
                        if derived_bytes>8000000:
                            raise ContractError('Derived MSE byte limit exceeded')
                        if len(raw)!=item['byte_length'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
                            raise ContractError('Derived MSE buffer checksum mismatch')
                        item['body']=base64.b64encode(raw).decode()
            payload['mse_buffer_reference']=mse
        worker=capture['data'].get('worker_media_reference')
        if worker:
            worker=json.loads(json.dumps(worker))
            worker_bytes=0
            for record in worker.get('records',[]):
                for item in record.get('buffers',[]):
                    raw=self.store.read_blob(item['artifact_id'])
                    worker_bytes+=len(raw)
                    if worker_bytes>8000000 or len(raw)!=item['byte_length'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
                        raise ContractError('Derived worker media checksum or byte limit mismatch')
                    item['body']=base64.b64encode(raw).decode()
            derived_bytes+=worker_bytes
            payload['worker_media_reference']=worker
        if derived_bytes+sum(len(base64.b64decode(a['body'])) for a in assets)>64000000:
            raise ContractError('Combined frozen resource budget exceeded')
        directory=self.results/'origin_inputs';directory.mkdir(parents=True,exist_ok=True)
        path=directory/(hashlib.sha256((campaign+ident).encode()).hexdigest()+'.json')
        raw=canonical(payload)
        if len(raw.encode())>96*1024*1024:
            raise ContractError('Original-origin manifest exceeds limit')
        if path.exists() and path.read_text()!=raw:
            raise EnvironmentChanged('Original-origin manifest changed after registration')
        path.write_text(raw,encoding='utf-8')
        return str(path),{'version':version,'manifest_sha256':hashlib.sha256(raw.encode()).hexdigest(),
                         'widget_adapters':widget_adapters,
                         'input_document_sha256':hashlib.sha256(source.encode()).hexdigest(),
                         'rendered_document_sha256':hashlib.sha256(rendered_document.encode()).hexdigest(),
                         'resource_map':{a['url']:a['url'] for a in assets},'resource_selection':'recorded-media-ranges-v2-css-header-variants-v1-other-last-entry-v1',
                         'excluded_unmapped_encoded_ranges':unsupported,'response_body_policy':'browser-response-body-v1','native_hls_selection_policy':'latest-native-hls-entity-v1','native_hls_selections':hls_choices,'redirect_alias_policy':'identical-recorded-resource-chains-v1','duplicate_resources':duplicates,'document_resource_selection':'injected-document-v1','excluded_navigation_responses':navigation,'excluded_ephemeral_resources':ephemeral,'opaque_resource_policy':'recorded-opaque-resource-exclusion-v1','scope':capture['data']['scope']}

    def audit(self, capture, source, campaign, ident, config):
        self.verify_runtime(campaign)
        manifest, replay = self.origin_manifest(capture, source, campaign, ident, config)
        try:
            result = self.post_snapshot({
                'manifest_path': manifest,
                'axe_standard': config.get('axe_standard', 'wcag22aa'),
            }, campaign, ident, source)
        finally:
            # Transport copies are reconstructible from immutable capture blobs.
            path = Path(manifest)
            if path.parent.resolve() == (self.results / 'origin_inputs').resolve() and not path.is_symlink():
                path.unlink(missing_ok=True)
        item = result['results'][0]
        artifacts = {}
        for key, value in (('axe',item.get('axe',{}).get('raw_path')), ('lighthouse',item.get('lighthouse',{}).get('raw_path')),
                           ('taxonomy_supplement',item.get('taxonomy_supplement_path')), ('rendered',item.get('source_snapshot_path')), ('screenshot',item.get('screenshot_path'))):
            if value:
                mime = 'image/jpeg' if key == 'screenshot' else 'text/html' if key == 'rendered' else 'application/json'
                artifacts[key] = self.store.blob(self.file(value), key+'_audit', campaign, mime)['id']
        segment_evidence=item.get('transport',{}).get('capture_segments')
        if segment_evidence:
            recorded=[]
            for segment in segment_evidence['segments']:
                blob=self.store.blob(self.file(segment['path']),'desktop_audit_segment',campaign,'image/jpeg')
                recorded.append({k:v for k,v in segment.items() if k!='path'}|{'artifact_id':blob['id']})
            artifacts['segments']=self.store.blob(canonical({'version':segment_evidence['version'],'complete':segment_evidence['complete'],'segments':recorded}),'desktop_segment_manifest',campaign,'application/json')['id']
        failures = json.loads(self.store.read_blob(artifacts['axe'])).get('violations',[]) if 'axe' in artifacts else []
        failures = [f for f in failures if any(str(tag).startswith('wcag') for tag in f.get('tags',[]))]
        from .html_tools import axe_failure_evidence,lighthouse_failure_evidence
        patch_failures=axe_failure_evidence(item.get('axe',{}).get('raw_path'),12)
        lighthouse_failures=lighthouse_failure_evidence(item.get('lighthouse',{}).get('raw_path'),8)
        syntax = self.post('/harness/validate', {'document':source})
        from .syntax_policy import localize
        syntax = localize(syntax, source, capture['data']['captured_url'])
        return self.store.append('audit', {'status':item['status'], 'error':item.get('error'),
                  'axe':item.get('axe',{}).get('wcag_violations'), 'lighthouse':item.get('lighthouse',{}).get('accessibility_score'),
                  'failures':failures, 'patch_failures':patch_failures,'lighthouse_failures':lighthouse_failures,
                  'syntax':syntax, 'artifacts':artifacts, 'replay':replay | {'uncaptured':item.get('transport',{}).get('missing_resources',[]),'diagnostics':item.get('transport',{})},
                  'environment':result.get('environment',result.get('metadata')), 'raw_result':item}, campaign, ident)

    def replay_check(self,capture,source,campaign,ident,audit):
        try:return self.store.get(ident)
        except KeyError:pass
        from .replay_admission import compare
        observed=audit['data'].get('raw_result',{}).get('transport',{}).get('visible')
        failure='Same-document audit lacks visible evidence'
        result=compare(capture['data'].get('visible'),observed)
        if observed is None:result['error']=failure
        return self.store.append('replay_admission',result|{'capture_id':capture['id'],'audit_id':audit['id'],
            'original':capture['data'].get('visible'),'replayed':observed},campaign,ident)
