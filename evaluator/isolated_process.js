"use strict";
const fs = require("node:fs");
const { spawn } = require("node:child_process");

function processIdentity(pid) {
  try {
    const stat = fs.readFileSync(`/proc/${pid}/stat`, "utf8");
    const fields = stat.slice(stat.lastIndexOf(")") + 2).split(" ");
    return { pid, parent: Number(fields[1]), group: Number(fields[2]), start: fields[19] };
  } catch { return null; }
}

function descendants(rootPid, owned) {
  if (process.platform !== "linux") return;
  const processes = fs.readdirSync("/proc").filter(name => /^\d+$/.test(name))
    .map(name => processIdentity(Number(name))).filter(Boolean);
  const parents = new Set([rootPid, ...[...owned.values()].filter(
    entry => processIdentity(entry.pid)?.start === entry.start).map(entry => entry.pid)]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const entry of processes) {
      if (parents.has(entry.parent) && !parents.has(entry.pid)) {
        parents.add(entry.pid); owned.set(entry.pid, entry); changed = true;
      }
    }
  }
}

/** Bound audits and own their browser descendants, including separate groups.
 * /proc start times prevent signalling reused PIDs. Private IPC identifies a
 * browser only when it belongs to this worker. Errors never become zero scores.
 */
function runIsolatedNode(args, { timeoutMs = 180000, maxBufferBytes = 100 * 1024 * 1024 } = {}) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error("A positive evaluator deadline is required");
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, {
      detached: process.platform !== "win32", stdio: ["ignore", "pipe", "pipe", "ipc"]
    });
    const owned = new Map(); const leaders = new Map();
    const chunks = []; const errors = []; let bytes = 0; let settled = false;
    const remember = () => { if (child.pid) descendants(child.pid, owned); };
    const cleanup = () => {
      remember();
      for (const entry of leaders.values()) {
        const current = processIdentity(entry.pid);
        if (current?.start === entry.start && current.group === entry.pid) {
          try { process.kill(-entry.pid, "SIGKILL"); } catch {}
        }
      }
      for (const entry of [...owned.values()].reverse()) {
        if (processIdentity(entry.pid)?.start === entry.start) {
          try { process.kill(entry.pid, "SIGKILL"); } catch {}
        }
      }
      if (child.pid && process.platform !== "win32") {
        try { process.kill(-child.pid, "SIGKILL"); } catch {}
      } else { child.kill("SIGKILL"); }
    };
    const finish = (error, output) => {
      if (settled) return;
      settled = true; clearTimeout(deadline); clearInterval(scan); cleanup();
      if (error) reject(error); else resolve(output);
    };
    const scan = setInterval(remember, 250); scan.unref();
    const deadline = setTimeout(() => finish(new Error(`Evaluator timeout after ${timeoutMs} ms`)), timeoutMs);
    child.on("message", message => {
      if (message?.type !== "browser_pid" || !Number.isInteger(message.pid) || message.pid <= 1) return;
      remember();
      const entry = owned.get(message.pid);
      if (entry) leaders.set(entry.pid, entry);
    });
    for (const [stream, target] of [[child.stdout, chunks], [child.stderr, errors]]) {
      stream.on("data", chunk => {
        bytes += chunk.length;
        if (bytes > maxBufferBytes) finish(new Error("Evaluator output exceeded the buffer limit"));
        else target.push(chunk);
      });
    }
    child.on("error", error => finish(error));
    // A browser holding an inherited pipe must not prevent process cleanup.
    child.on("exit", cleanup);
    child.on("close", (code, signal) => {
      const detail = Buffer.concat(errors).toString("utf8").trim();
      if (code !== 0) finish(new Error(detail || `Evaluator exited with ${signal || code}`));
      else finish(null, Buffer.concat(chunks).toString("utf8"));
    });
  });
}

module.exports = { runIsolatedNode, processIdentity };
