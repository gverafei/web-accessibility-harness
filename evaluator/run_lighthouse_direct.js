const lighthouse = require("./axe_name_guard").lighthouse().default;
const chromeLauncher = require("chrome-launcher");
const { extractAccessibilityScore } = require("./lighthouse_score");

async function runLighthouseDirect(url) {
  const chrome = await chromeLauncher.launch({
    chromePath: "/usr/bin/chromium",
    chromeFlags: ["--headless", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
  });
  if (process.send) process.send({ type: "browser_pid", pid: chrome.pid });
  try {
    const runnerResult = await lighthouse(url, {
      logLevel: "error", output: "json", onlyCategories: ["accessibility"], port: chrome.port,
      ...require('./desktop_profile').lighthouseFlags()
    });
    const lhr = runnerResult.lhr;
    return {
      summary: { accessibility_score: extractAccessibilityScore(lhr) },
      raw: lhr
    };
  } finally {
    try {
      await chrome.kill();
    } catch {
      // The supervisor still owns this browser group if graceful cleanup fails.
    }
  }
}

async function main() {
  try {
    process.stdout.write(JSON.stringify(await runLighthouseDirect(process.argv[2])));
  } catch (error) {
    process.stderr.write(error?.stack || error?.message || String(error));
    process.exitCode = 1;
  } finally {
    if (process.connected) process.disconnect();
  }
}

if (require.main === module) main();

module.exports = { runLighthouseDirect };
