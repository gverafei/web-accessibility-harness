const path = require("path");
const { runIsolatedNode } = require("./isolated_process");
const { extractAccessibilityScore } = require("./lighthouse_score");

async function runLighthouse(url) {
  let stdout;
  try {
    stdout = await runIsolatedNode([path.join(__dirname, "run_lighthouse_direct.js"), url]);
  } catch (error) {
    throw new Error(`Isolated Lighthouse failure: ${error.message}`, { cause: error });
  }
  try { return JSON.parse(stdout); }
  catch (error) { throw new Error(`Isolated Lighthouse returned invalid JSON: ${error.message}`, { cause: error }); }
}

module.exports = { extractAccessibilityScore, runLighthouse };
