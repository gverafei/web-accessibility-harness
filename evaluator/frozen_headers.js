'use strict';

// Playwright joins repeated response headers with LF. Chromium Fetch requires
// separate entries, while Route.fulfill uses a map. CSP explicitly permits a
// comma-separated policy list, with every policy enforced independently.
const VERSION = 'frozen-response-headers-v2';
const POLICY_HEADERS = new Set([
  'content-security-policy',
  'content-security-policy-report-only',
]);

function entries(headers) {
  const result = [];
  for (const [name, rawValue] of Object.entries(headers)) {
    const value = String(rawValue);
    if (value.includes('\r')) {
      throw new Error('Unexpected carriage return in frozen header: ' + name);
    }
    if (value.includes('\n') && !POLICY_HEADERS.has(name.toLowerCase())) {
      throw new Error('Unsupported repeated frozen header: ' + name);
    }
    for (const policy of value.split('\n')) {
      // Ordinary HTTP fields can have an empty value. Preserve that response
      // exactly; an empty CORS field must not become an allowed origin.
      if (POLICY_HEADERS.has(name.toLowerCase()) && !policy.trim()) {
        throw new Error('Empty frozen header value: ' + name);
      }
      result.push({ name, value: policy });
    }
  }
  return result;
}

function routeHeaders(headers) {
  const result = {};
  for (const { name, value } of entries(headers)) {
    result[name] = result[name] ? result[name] + ', ' + value : value;
  }
  return result;
}

module.exports = { VERSION, entries, routeHeaders };
