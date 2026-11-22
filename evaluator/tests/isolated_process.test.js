const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");
const { runIsolatedNode, processIdentity } = require("../isolated_process");

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

test("isolated audit preserves its complete output", async () => {
  assert.equal(await runIsolatedNode(["-e", 'process.stdout.write("{\\"score\\":93}")']), '{"score":93}');
});

test("original audit error is not replaced with a zero result", async () => {
  await assert.rejects(runIsolatedNode(["-e", 'process.stderr.write("NO_FCP fixture");process.exit(1)']), /NO_FCP fixture/);
});

test("an excessive audit report has a bounded buffer", async () => {
  await assert.rejects(runIsolatedNode(["-e", 'process.stdout.write("x".repeat(4096));setInterval(()=>{},1000)'],
    { maxBufferBytes: 1024, timeoutMs: 2000 }), /buffer limit/);
});

test("a worker that ignores graceful termination still has a hard deadline", async () => {
  const start = Date.now();
  await assert.rejects(runIsolatedNode(["-e", 'process.on("SIGTERM",()=>{});setInterval(()=>{},1000)'],
    { timeoutMs: 300 }), /timeout after 300/);
  assert.ok(Date.now() - start < 2000);
});

for (const ending of ["success", "error", "timeout"]) {
  test(`a separately detached browser is removed on ${ending}`, { skip: process.platform !== "linux" }, async () => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), "warp-process-test-"));
    const pidFile = path.join(directory, "browser.pid");
    const code = `
      const {spawn}=require('node:child_process'); const fs=require('node:fs');
      const browser=spawn(process.execPath,['-e','process.on("SIGTERM",()=>{});setInterval(()=>{},1000)'],{detached:true,stdio:'ignore'});
      process.send({type:'browser_pid',pid:browser.pid});
      fs.writeFileSync(process.argv[1],String(browser.pid));
      ${ending === 'timeout' ? 'setInterval(()=>{},1000);' : `setTimeout(()=>{process.stdout.write('ok');process.exit(${ending === 'success' ? 0 : 1})},400);`}
    `;
    try {
      const audit = runIsolatedNode(["-e", code, pidFile], { timeoutMs: 1500 });
      if (ending === "success") assert.equal(await audit, "ok");
      else await assert.rejects(audit, ending === "timeout" ? /timeout/ : /exited/);
      const pid = Number(fs.readFileSync(pidFile, "utf8"));
      for (let i = 0; i < 30 && processIdentity(pid); i++) await delay(50);
      assert.equal(processIdentity(pid), null, "the browser was not killed/reaped");
    } finally { fs.rmSync(directory, { recursive: true, force: true }); }
  });
}

test("cleanup cannot signal a browser belonging to another audit", { skip: process.platform !== "linux" }, async () => {
  const unrelated = spawn(process.execPath, ["-e", 'setInterval(()=>{},1000)'], { detached: true, stdio: "ignore" });
  try {
    await assert.rejects(runIsolatedNode(["-e", `process.send({type:'browser_pid',pid:${unrelated.pid}});setInterval(()=>{},1000)`],
      { timeoutMs: 500 }), /timeout/);
    assert.ok(processIdentity(unrelated.pid));
  } finally { try { process.kill(-unrelated.pid, "SIGKILL"); } catch {} }
});
