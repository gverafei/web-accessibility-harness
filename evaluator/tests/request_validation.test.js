const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {once} = require('node:events');

test('missing or unparsed evaluation bodies return the existing JSON 400 contract', async () => {
  // The service uses its fixed internal port in the isolated test container.
  const port = 3000;
  const server = spawn(process.execPath, [path.join(__dirname, '../server.js')], {
    env: {...process.env, WAVE_API_KEY: '', OPENROUTER_API_KEY: ''},
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  let errors = '';
  server.stderr.on('data', chunk => { errors = (errors + chunk).slice(-2000); });
  const exited = once(server, 'exit');
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      try { ready = (await fetch(`http://127.0.0.1:${port}/health`)).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    assert.ok(ready, errors);
    const health = await (await fetch(`http://127.0.0.1:${port}/health`)).json();
    assert.equal(health.axe_version, require('../package.json').dependencies['@axe-core/playwright']);
    assert.equal(health.runtime.html_validator_version,require('../package.json').dependencies['html-validate']);
    assert.match(health.runtime.source_files['harness_evidence.js'],/^[a-f0-9]{64}$/);
    assert.ok(health.runtime.environment.chromium_version!=='unknown');
    for (const options of [
      {},
      {headers: {'Content-Type': 'application/json'}},
      {headers: {'Content-Type': 'application/json'}, body: '{}'},
      {headers: {'Content-Type': 'text/plain'}, body: 'unparsed'},
    ]) {
      const response = await fetch(`http://127.0.0.1:${port}/evaluate`, {method: 'POST', ...options});
      assert.equal(response.status, 400);
      assert.match(response.headers.get('content-type'), /application\/json/);
      assert.deepEqual(await response.json(), {error: 'experiment_id y urls son requeridos'});
    }
  } finally {
    server.kill('SIGTERM');
    await exited;
  }
});
