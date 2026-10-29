'use strict';
const crypto=require('node:crypto');
const VERSION='observed-media-init-prefix-v1',MAX_BYTES=8000000;
function extract(bytes,container){
 if(!Buffer.isBuffer(bytes)||bytes.length<8||bytes.length>MAX_BYTES)throw Error('Invalid observed media byte bound');
 let end;
 if(container==='video/mp4'||container==='audio/mp4')end=mp4(bytes);
 else if(container==='video/webm'||container==='audio/webm')end=webm(bytes);
 else throw Error('Unsupported initialization container');
 const body=Buffer.from(bytes.subarray(0,end));
 return{version:VERSION,container,byte_length:body.length,sha256:crypto.createHash('sha256').update(body).digest('hex'),body};
}
function mp4(bytes){
 let at=0,ftyp=false,moov=false;
 for(let count=0;count<256&&at<bytes.length;count++){
  if(at+8>bytes.length)throw Error('Truncated MP4 box');
  let size=bytes.readUInt32BE(at),header=8;const type=bytes.toString('ascii',at+4,at+8);
  // Media begins here. Its payload may be incomplete, but all preceding
  // initialization boxes must already be complete and unambiguous.
  if(type==='moof'||type==='mdat'){if(!ftyp||!moov)throw Error('Missing MP4 initialization');return at;}
  if(size===1){if(at+16>bytes.length)throw Error('Truncated MP4 extended size');const wide=bytes.readBigUInt64BE(at+8);if(wide>BigInt(bytes.length))throw Error('MP4 size exceeds observed bytes');size=Number(wide);header=16;}
  if(size<header||at+size>bytes.length)throw Error('Incomplete MP4 initialization box');
  if(type==='ftyp'){if(ftyp||at!==0||size<header+8)throw Error('Invalid MP4 file type');ftyp=true;}
  else if(type==='moov'){if(!ftyp||moov)throw Error('Invalid MP4 movie order');moov=true;}
  else if(!['free','skip','wide','sidx','styp','pdin','uuid'].includes(type))throw Error('Unsupported MP4 initialization box');
  at+=size;
 }
 if(at!==bytes.length||!ftyp||!moov)throw Error('Incomplete MP4 initialization');
 return at;
}
function webm(bytes){
 function vint(at,id){
  if(at>=bytes.length||bytes[at]===0)throw Error('Invalid EBML integer');
  let n=1,mask=128;while(!(bytes[at]&mask)){n++;mask>>=1;}
  if(n>(id?4:8)||at+n>bytes.length)throw Error('Truncated EBML integer');
  let value=BigInt(id?bytes[at]:bytes[at]&(mask-1));for(let i=1;i<n;i++)value=(value<<8n)|BigInt(bytes[at+i]);
  return{n,value,unknown:!id&&value===(1n<<BigInt(7*n))-1n};
 }
 function element(at,limit,allowUnknown=false){
  const id=vint(at,true),size=vint(at+id.n,false),body=at+id.n+size.n;
  if(size.unknown&&!allowUnknown)throw Error('Unknown child EBML size');
  if(!size.unknown&&size.value>BigInt(MAX_BYTES))throw Error('EBML size exceeds bound');
  const end=size.unknown?limit:allowUnknown?Math.min(limit,body+Number(size.value)):body+Number(size.value);
  if(body>limit||end>limit||end<body)throw Error('Truncated EBML element');
  return{id:id.value,body,end};
 }
 const header=element(0,bytes.length);if(header.id!==0x1a45dfa3n)throw Error('Missing EBML header');
 let docType=false,at=header.body,count=0;
 while(at<header.end){if(++count>256)throw Error('EBML header count exceeded');const child=element(at,header.end);if(child.id===0x4282n){if(docType||bytes.toString('utf8',child.body,child.end)!=='webm')throw Error('Unsupported EBML document type');docType=true;}at=child.end;}
 if(!docType)throw Error('Missing WebM document type');
 const segment=element(header.end,bytes.length,true);if(segment.id!==0x18538067n)throw Error('Missing WebM Segment');
 at=segment.body;let info=false,tracks=false;
 for(count=0;count<256&&at<segment.end;count++){
  // A Cluster is recognized only at the Segment's direct-child boundary.
  const id=vint(at,true);
  if(id.value===0x1f43b675n){if(!info||!tracks)throw Error('Missing WebM initialization');return at;}
  const child=element(at,segment.end);
  if(child.id===0x1549a966n){if(info)throw Error('Duplicate WebM Info');info=true;}
  else if(child.id===0x1654ae6bn){if(tracks)throw Error('Duplicate WebM Tracks');tracks=true;}
  else if(![0x114d9b74n,0xecn,0xbfn].includes(child.id))throw Error('Unsupported WebM initialization element');
  at=child.end;
 }
 if(at!==segment.end||!info||!tracks)throw Error('Incomplete WebM initialization');
 return at;
}
module.exports={VERSION,MAX_BYTES,extract};
