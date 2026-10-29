'use strict';

const VERSION = 'recorded-stylesheet-cors-variants-v1';
const SECURITY_HEADERS = [
  'content-security-policy',
  'content-security-policy-report-only',
  'cross-origin-resource-policy',
  'cross-origin-embedder-policy',
  'x-content-type-options',
];

function header(headers, name) {
  return Object.entries(headers || {}).find(([key]) => key.toLowerCase() === name)?.[1];
}

function compatible(reference, candidate) {
  return reference.mime === candidate.mime && reference.sha256 === candidate.sha256 &&
    (reference.http_status ?? 200) === 200 && (candidate.http_status ?? 200) === 200 &&
    SECURITY_HEADERS.every(name =>
      header(reference.headers, name) === header(candidate.headers, name));
}

function choose(selected, variants, requestHeaders) {
  const origin = header(requestHeaders, 'origin');
  if (!selected || !/^text\/css(?:;|$)/i.test(selected.mime || '') || !origin) {
    return selected;
  }
  const allowed = header(selected.headers, 'access-control-allow-origin');
  if (allowed === origin || allowed === '*') return selected;
  // A later no-CORS fetch can have the same bytes but no CORS response fields.
  // Return one complete, observed response matching the requesting origin.
  // Never synthesize permissions, mix headers, or substitute a different body.
  const candidates = (variants || []).filter(candidate => compatible(selected, candidate));
  return candidates.find(candidate =>
    header(candidate.headers, 'access-control-allow-origin') === origin) ||
    candidates.find(candidate =>
      header(candidate.headers, 'access-control-allow-origin') === '*') || selected;
}

module.exports = { VERSION, choose };
