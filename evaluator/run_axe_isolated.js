const path = require("node:path");
const { runIsolatedNode } = require("./isolated_process");
const { loadPolicy } = require("./run_axe");

const BROWSER_KEYS = [
  'page_load_timeout_ms', 'axe_hard_timeout_ms', 'network_idle_timeout_ms',
  'page_settle_delay_ms', 'dom_stability_window_ms', 'dom_stability_timeout_ms',
  'enable_lazy_load_scroll', 'scroll_step_px', 'scroll_delay_ms', 'max_scroll_steps'
];
function browserRuntimeConfig(config = {}) {
  return Object.fromEntries(BROWSER_KEYS.filter(key => Object.hasOwn(config, key))
    .map(key => [key, config[key]]));
}

async function runAxeIsolated(url, screenshotPath, options = {}) {
  options = {...options, runtimeConfig: browserRuntimeConfig(options.runtimeConfig || {})};
  const policy = loadPolicy(options.runtimeConfig || {});
  let output;
  try {
    output = await runIsolatedNode([
      path.join(__dirname, "run_axe_direct.js"), JSON.stringify({ url, screenshotPath, options })
    ], { timeoutMs: Math.max(1, policy.axe_hard_timeout_ms) + 10000 });
  } catch (error) {
    throw new Error(`Isolated Axe failure: ${error.message}`, { cause: error });
  }
  try { return JSON.parse(output); }
  catch (error) { throw new Error(`Isolated Axe returned invalid JSON: ${error.message}`, { cause: error }); }
}

module.exports = { runAxeIsolated, browserRuntimeConfig };
