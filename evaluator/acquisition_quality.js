/* Eligibility is deterministic and independent of Axe/Lighthouse outcomes. */
function validateQualityPolicy(value = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid acquisition quality policy');
  const allowed = new Set(['version', 'require_complete_evidence', 'exclude_explicit_content', 'excluded_hosts']);
  if (Object.keys(value).some(key => !allowed.has(key))) throw new Error('Unknown acquisition quality policy field');
  for (const key of ['require_complete_evidence', 'exclude_explicit_content']) {
    if (value[key] !== undefined && typeof value[key] !== 'boolean') throw new Error(`Invalid ${key}`);
  }
  if (value.excluded_hosts !== undefined && (!Array.isArray(value.excluded_hosts) ||
      value.excluded_hosts.length > 100 || value.excluded_hosts.some(host => typeof host !== 'string' || !/^[a-z0-9.-]+$/i.test(host)))) {
    throw new Error('Invalid excluded hosts');
  }
  return value;
}

function pageRejection({url, title = '', body = '', httpStatus = 200}, policy = {}) {
  if (httpStatus >= 400) return `Acquisition excluded: main-document HTTP ${httpStatus}.`;
  const heading = title.trim();
  if (/^(?:access (?:to this page has been )?denied|403\b|404\b|HTTP Status [45]\d\d\b|service unavailable|bot verification|challenge validation|security verification|checking your browser|verify you are human)/i.test(heading) ||
      /(?:confirm that you are (?:a )?human|verifying that you are not a robot|there was an error processing your request)/i.test(body) && body.length < 1200) {
    return 'Acquisition excluded: publisher error or verification interstitial.';
  }
  const host = new URL(url).hostname.toLowerCase().replace(/^www\./, '');
  if ((policy.excluded_hosts || []).some(excluded => host === excluded || host.endsWith('.' + excluded))) {
    return 'Acquisition excluded: domain outside the prespecified content scope.';
  }
  if (policy.exclude_explicit_content && /porn|hentai|fetish|xxx|sex videos|adult videos|adultfriendfinder|feetplaza|bokep|phim\s*sex|xvideos|rule34video|sexviet|adult game|エロ漫画|成人(?:视频|大片)|黄色视频网站|эротическ|порно|الاباحية|سكس العرب|เรื่องเสียว|야동사이트|live sexcams/i.test(host + ' ' + heading)) {
    return 'Acquisition excluded: explicit/adult content outside the dataset scope.';
  }
  return null;
}

function evidenceRejection(result, policy = {}) {
  if (!policy.require_complete_evidence) return null;
  if (!result.response_html || !result.response_html.trim()) return 'Acquisition excluded: original main-document response body unavailable.';
  if (!result.html || !result.html.trim()) return 'Acquisition excluded: rendered HTML unavailable.';
  if (!result.screenshot_path) return 'Acquisition excluded: screenshot evidence unavailable.';
  return null;
}
module.exports = {validateQualityPolicy, pageRejection, evidenceRejection};
