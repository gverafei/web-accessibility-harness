'use strict';
const VERSION='resource-evidence-limits-v7';
function resourceLimit(mime){if(/^(text\/css|(?:application|text)\/(?:javascript|ecmascript|x-javascript))(?:;|$)/i.test(mime||''))return 16000000;return /^(image|video|audio)\//i.test(mime||'')?8000000:2000000;}
const DOCUMENT_BYTES=8000000;
const TOTAL_RESOURCE_BYTES=64000000;
// Transport entries include captured native responses and bounded recovery
// resources. This cap never increases acquisition requests or byte budgets.
const SNAPSHOT_ASSET_ENTRIES=2000;
const MANIFEST_BYTES=96*1024*1024;
module.exports={VERSION,resourceLimit,DOCUMENT_BYTES,TOTAL_RESOURCE_BYTES,MANIFEST_BYTES,SNAPSHOT_ASSET_ENTRIES};
