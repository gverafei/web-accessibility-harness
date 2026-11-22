// Bounded real-Chromium pilot. No experiment records or paid calls are created.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { runAxeIsolated } = require("../run_axe_isolated");
const { runLighthouse } = require("../run_lighthouse");
const { runIsolatedNode } = require("../isolated_process");

function browserProcesses() {
  return fs.readdirSync('/proc').filter(name => /^\d+$/.test(name)).filter(pid => {
    try { return /^(chromium|chrome_crashpad)/.test(fs.readFileSync(`/proc/${pid}/comm`, 'utf8')); }
    catch { return false; }
  });
}

async function assertClean() {
  for (let i = 0; i < 40 && browserProcesses().length; i++) {
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(browserProcesses().length, 0, 'Chromium processes remain after the audit');
}

async function main() {
  assert.equal(browserProcesses().length, 0, 'Run only while the evaluator is idle');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'warp-browser-pilot-'));
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end('<!doctype html><html lang="en"><head><title>Cleanup pilot</title></head><body><header><h1>Browser cleanup pilot</h1></header><main><p>A controlled public-style document used to check complete evaluator results and cleanup, not to contribute a research observation.</p><nav aria-label="Examples"><a href="#one">First section</a><a href="#two">Second section</a></nav><section id="one"><h2>First</h2><p>Measured evidence remains unchanged.</p></section><section id="two"><h2>Second</h2><p>Cleanup happens after success or failure.</p></section></main><footer>End of fixture.</footer></body></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  try {
    for (let i = 0; i < 3; i++) {
      const [axe, lh] = await Promise.all([
        runAxeIsolated(url, path.join(directory, `page-${i}.jpg`), {
          standard: 'wcag22aa', includeBestPractices: true,
          runtimeConfig: { enable_lazy_load_scroll: false }
        }), runLighthouse(url)
      ]);
      assert.ok(Array.isArray(axe.raw.violations));
      assert.ok(Number.isFinite(lh.summary.accessibility_score));
      await assertClean();
      console.log(JSON.stringify({ case: `successful-audit-${i+1}`, lighthouse: lh.summary.accessibility_score, remaining_browser_processes: 0 }));
    }
    for (const ending of ['error', 'timeout']) {
      const code = `
        const launcher=require('chrome-launcher');
        (async()=>{const chrome=await launcher.launch({chromePath:'/usr/bin/chromium',chromeFlags:['--headless','--no-sandbox','--disable-gpu','--disable-dev-shm-usage']});
        process.send({type:'browser_pid',pid:chrome.pid});
        ${ending === 'error' ? "process.stderr.write('Intentional pilot failure');setTimeout(()=>process.exit(1),300);" : 'setInterval(()=>{},1000);'} })();
      `;
      await assert.rejects(runIsolatedNode(['-e', code], { timeoutMs: 4000 }),
        ending === 'error' ? /Intentional pilot failure/ : /timeout/);
      await assertClean();
      console.log(JSON.stringify({ case: ending, remaining_browser_processes: 0 }));
    }
  } finally {
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
