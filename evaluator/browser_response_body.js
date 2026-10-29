'use strict';
const VERSION='browser-response-body-v1';
const retained=['content-type','content-encoding','content-length','content-range','accept-ranges','access-control-allow-origin','access-control-allow-credentials','cross-origin-resource-policy','content-security-policy'];
// Playwright returns the decoded response entity; HTTP byte ranges can refer
// to a compressed wire representation. Only an explicitly encoded full wire
// range establishes a complete logical entity. Partial encoded ranges cannot
// establish logical offsets and are never reconstructed here.
function observed(status,headers,body){
 const original=Object.fromEntries(Object.entries(headers).filter(([k])=>retained.includes(k))),active=Object.fromEntries(Object.entries(original).filter(([k])=>!['content-type','content-encoding','content-length'].includes(k)));
 const encoding=(headers['content-encoding']||'').trim().toLowerCase(),range=/^bytes (\d+)-(\d+)\/(\d+)$/.exec(headers['content-range']||'');
 const encoded=encoding&&encoding!=='identity';
 const full=range&&range.slice(1).every(v=>Number.isSafeInteger(Number(v)))&&Number(range[1])===0&&Number(range[2])+1===Number(range[3])&&Number(range[3])>0;
 const supported=encoded&&encoding.split(',').every(v=>['gzip','br','deflate'].includes(v.trim()));
 if(status===206&&encoded){
  if(!supported||!full)return {http_status:status,headers:active,body_representation:{version:VERSION,kind:'unsupported_encoded_range',logical_bytes:body.length,native_http_status:status,native_headers:original,reason:'Encoded partial response lacks complete logical byte offsets'}};
  if(!Buffer.isBuffer(body)||!body.length)throw Error('Empty decoded complete response');
  delete active['content-range'];delete active['accept-ranges'];
  return {http_status:200,headers:active,body_representation:{version:VERSION,kind:'decoded_complete_entity',logical_bytes:body.length,native_http_status:status,native_headers:original,wire_range_bytes:Number(range[3]),scope:'Complete wire range decoded by the browser; no partial or invented bytes'}};
 }
 return {http_status:status,headers:active,body_representation:{version:VERSION,kind:'browser_response_entity',logical_bytes:body.length,native_http_status:status,native_headers:original}};
}
module.exports={VERSION,observed};
