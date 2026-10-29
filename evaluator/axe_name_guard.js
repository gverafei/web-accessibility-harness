'use strict';

const fs = require('node:fs');
const crypto = require('node:crypto');
const VERSION = 'axe-implicit-name-cycle-guard-v1';
const ORIGINAL_SHA256 = '138a93a4ce7b7c6c08ed84144e45dcd8cc36d2d4ff8ed673619faf0406906d88';
let cached;

function source() {
  if (cached) return cached;
  const original = fs.readFileSync(require.resolve('axe-core/axe.js'), 'utf8');
  const hash = crypto.createHash('sha256').update(original).digest('hex');
  if (require('axe-core').version !== '4.13.0' || hash !== ORIGINAL_SHA256) {
    throw new Error('Review the accessible-name cycle guard against the installed Axe source');
  }
  const start = original.indexOf('function hasAccessibleName(vNode) {');
  const end = original.indexOf('\n    var implicitHtmlRoles', start);
  if (start < 0 || end < start) throw new Error('Axe name guard anchor unavailable');
  const functionSource = original.slice(start, end);
  const closing = functionSource.lastIndexOf('}');
  // A section/form can refer to itself while Axe is determining its implicit
  // role. Break only this re-entrant role lookup, preserving the DOM and the
  // remaining accessible-name computation, rules and audit options.
  const guarded = functionSource.slice(0, closing)
    .replace('{', '{\n      if (implicitNameStack.has(vNode)) return false;\n'
      + '      implicitNameStack.add(vNode);\n      try {')
    + '\n      } finally { implicitNameStack.delete(vNode); }\n    }'
    + functionSource.slice(closing + 1);
  cached = original.slice(0, start) + 'var implicitNameStack = new WeakSet();\n    '
    + guarded + original.slice(end);
  return cached;
}

function lighthouse() {
  // Lighthouse reads Axe at module initialization. Replace only that exact
  // file read in this isolated worker, then restore fs before any async work.
  const filename = require.resolve('axe-core/axe.min.js');
  const read = fs.readFileSync;
  fs.readFileSync = function (file, options) {
    if (String(file) === filename) {
      return typeof options === 'string' || options?.encoding ? source() : Buffer.from(source());
    }
    return read.apply(this, arguments);
  };
  try {
    const root = require('node:path').dirname(require.resolve('lighthouse'));
    require(require('node:path').join(root, 'lib/axe.js'));
    return require('lighthouse');
  }
  finally { fs.readFileSync = read; }
}

function provenance() {
  return {version: VERSION, original_axe_sha256: ORIGINAL_SHA256,
    injected_axe_sha256: crypto.createHash('sha256').update(source()).digest('hex'),
    document_modified: false, rules_disabled: []};
}

module.exports = {VERSION, source, lighthouse, provenance};
