const express = require("express");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { execSync } = require("child_process");

const { loadPolicy } = require("./run_axe");
const { runAxeIsolated: runAxe } = require("./run_axe_isolated");
const { runLighthouse } = require("./run_lighthouse");
const { safeFileName } = require("./file_names");

const app = express();
app.use(express.json({ limit: "20mb" }));

const RESULTS_DIR = "/results/raw";

function ensureDir(dirPath) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
}

function getCommandOutput(command) {
  try {
    return execSync(command, { encoding: "utf-8" }).trim();
  } catch {
    return "unknown";
  }
}

function getPackageVersion(packageName) {
  try {
    // Read installed metadata without a runtime package manager. Start at the
    // module entry point because some packages do not export package.json.
    let directory = path.dirname(require.resolve(packageName));
    while (directory !== path.dirname(directory)) {
      const manifest = path.join(directory, "package.json");
      if (fs.existsSync(manifest)) {
        const installed = JSON.parse(fs.readFileSync(manifest, "utf-8"));
        if (installed.name === packageName) return installed.version || "unknown";
      }
      directory = path.dirname(directory);
    }
    return "unknown";
  } catch {
    return "unknown";
  }
}

function getEnvironmentMetadata(executionSeconds, includeWave, axeStandard, axeIncludeBestPractices, runtimeConfig = {}) {
  const policy = loadPolicy(runtimeConfig);
  return {
    docker_web_image: process.env.DOCKER_WEB_IMAGE || "local-build",
    docker_evaluator_image: process.env.DOCKER_EVALUATOR_IMAGE || "local-build",
    python_version: null,
    node_version: getCommandOutput("node --version"),
    chromium_version: getCommandOutput("chromium --version"),
    cjk_font_package: getCommandOutput("apk info -v font-noto-cjk"),
    axe_version: getPackageVersion("@axe-core/playwright"),
    axe_name_guard: require('./axe_name_guard').provenance(),
    axe_standard: axeStandard,
    axe_include_best_practices: axeIncludeBestPractices,
    axe_counting_mode: "issue_instances",
    app_timezone: runtimeConfig.app_timezone || process.env.APP_TIMEZONE || "UTC",
    lighthouse_version: getPackageVersion("lighthouse"),
    desktop_profile:require('./desktop_profile').VERSION,
    viewport:{...require('./desktop_profile').viewport},
    form_factor:'desktop',
    openai_model: null,
    llm_provider: null,
    llm_model: null,
    page_load_timeout_ms: policy.page_load_timeout_ms,
    network_idle_timeout_ms: policy.network_idle_timeout_ms,
    page_settle_delay_ms: policy.page_settle_delay_ms,
    dom_stability_window_ms: policy.dom_stability_window_ms,
    dom_stability_timeout_ms: policy.dom_stability_timeout_ms,
    lazy_load_scroll: policy.lazy_load_scroll,
    scroll_step_px: policy.scroll_step_px,
    scroll_delay_ms: policy.scroll_delay_ms,
    max_scroll_steps: policy.max_scroll_steps,
    evaluator_concurrency: "axe+lighthouse per URL; Axe/Lighthouse isolated process supervision v1",
    execution_seconds: executionSeconds
  };
}

app.get("/health", (req, res) => {
  const source_files = Object.fromEntries(fs.readdirSync(__dirname).filter(name => name.endsWith('.js')).sort()
    .map(name => [name, crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname,name))).digest('hex')]));
  const environment=getEnvironmentMetadata(0,false,'wcag22aa',false);
  delete environment.execution_seconds;
  res.json({
    status: "ok",
    service: "accessibility-evaluator",
    axe_version: getPackageVersion("@axe-core/playwright"),
    runtime: {source_files, environment, html_validator_version:getPackageVersion('html-validate')}
  });
});

app.post('/harness/capture', async (req,res) => {
  try { const {capture} = require('./harness_evidence'); res.json(await capture(req.body.url, RESULTS_DIR)); }
  catch(error) { res.status(422).json(require('./harness_evidence').captureFailure(error)); }
});
app.post('/harness/freeze-source', async (req,res) => {
  try { const {capture} = require('./harness_evidence'); res.json(await capture(req.body.url, RESULTS_DIR, true, req.body.origin ? {origin:req.body.origin,document:req.body.document} : null)); }
  catch(error) { res.status(422).json(require('./harness_evidence').captureFailure(error)); }
});
app.post('/harness/replay-check', async (req,res) => {
  try {res.json(await require('./replay_admission').replayCheck(req.body.url));}
  catch(error) {res.status(422).json({error:error.message});}
});
app.post('/harness/origin-snapshot', async (req,res) => {
  const directory=path.join(RESULTS_DIR,'origin_'+crypto.randomUUID());
  try {
    const {isolated}=require('./origin_snapshot');
    const item=await isolated(req.body.manifest_path,directory,req.body.check_only===true);
    res.json(req.body.check_only===true ? item : {results:[item],environment:{
      ...getEnvironmentMetadata(0,false,req.body.axe_standard || 'wcag22aa',false),
      evaluator_concurrency:'Sequential capture, Axe and Lighthouse snapshot in one original-origin document',
      lighthouse_mode:'snapshot',viewport_width:1440,viewport_height:1000,
      transport_version:require('./origin_snapshot').VERSION,
      phase_evidence_version:require('./phase_evidence').VERSION}});
  } catch(error) {
    let instrumentStage;try{instrumentStage=JSON.parse(fs.readFileSync(path.join(directory,'instrument-stage.json'),'utf8'));}catch{}
    let settlement;try{settlement=JSON.parse(fs.readFileSync(path.join(directory,'resource-settlement.json'),'utf8'));}catch{}
    let documentChange;try{documentChange=JSON.parse(fs.readFileSync(path.join(directory,'supplement-document-change.json'),'utf8'));}catch{}
    res.status(422).json({error:error.message,failure_kind:'transport_error',instrument_stage:instrumentStage,resource_settlement:settlement,supplement_document_change:documentChange});
  }
});

app.post('/harness/validate', async (req,res) => {
  try { const {validateDocument} = require('./harness_evidence'); res.json(await validateDocument(req.body.document)); }
  catch(error) { res.status(422).json({error:error.message}); }
});

app.post("/evaluate", async (req, res) => {
  const experimentStart = Date.now();
  const {
    experiment_id,
    urls,
    axe_standard = "wcag22aa",
    axe_include_best_practices = false,
    runtime_config = {},
    quality_policy = {}
  } = req.body ?? {};

  if (!experiment_id || !Array.isArray(urls) || urls.length === 0) {
    return res.status(400).json({
      error: "experiment_id y urls son requeridos"
    });
  }
  const { validateQualityPolicy, evidenceRejection } = require('./acquisition_quality');
  try { validateQualityPolicy(quality_policy); }
  catch (error) { return res.status(400).json({error: error.message}); }

  ensureDir(RESULTS_DIR);

  const experimentDir = path.join(RESULTS_DIR, `experiment_${experiment_id}`);
  ensureDir(experimentDir);

  const results = [];

  for (const url of urls) {
    const itemStart = Date.now();
    const fileBase = safeFileName(url);
    const screenshotPath = path.join(experimentDir, `${fileBase}_page.jpg`);

    try {
      const sameDocument=quality_policy.require_complete_evidence===true&&!url.startsWith('http://dataset-server:8080/');
      const axeWork=runAxe(url, screenshotPath, {
          standard: axe_standard,
          includeBestPractices: true,
          runtimeConfig: runtime_config,
          qualityPolicy: quality_policy,
          lighthouseSnapshot:sameDocument
        });
      const [axeOutcome, lighthouseOutcome] = await Promise.allSettled([
        axeWork,
        sameDocument?axeWork.then(value=>value.lighthouse_result):runLighthouse(url)
      ]);

      if (axeOutcome.status === "rejected" || lighthouseOutcome.status === "rejected") {
        const failures = [];
        if (axeOutcome.status === "rejected") failures.push(`Axe: ${axeOutcome.reason.message}`);
        if (lighthouseOutcome.status === "rejected"&&!(sameDocument&&axeOutcome.status==='rejected')) failures.push(`Lighthouse: ${lighthouseOutcome.reason.message}`);
        throw new Error(failures.join(" | "));
      }

      const axeResult = axeOutcome.value;
      const lighthouseResult = lighthouseOutcome.value;
      const incomplete = evidenceRejection(axeResult, quality_policy);
      if (incomplete) throw new Error(incomplete);

      const axePath = path.join(experimentDir, `${fileBase}_axe.json`);
      const lighthousePath = path.join(experimentDir, `${fileBase}_lighthouse.json`);
      const sourceSnapshotPath = path.join(experimentDir, `${fileBase}_source.html`);
      const responseSourcePath = axeResult.response_html
        ? path.join(experimentDir, `${fileBase}_response.html`)
        : null;

      fs.writeFileSync(axePath, JSON.stringify(axeResult.raw, null, 2), "utf-8");
      fs.writeFileSync(lighthousePath, JSON.stringify(lighthouseResult.raw, null, 2), "utf-8");
      fs.writeFileSync(sourceSnapshotPath, axeResult.html, "utf-8");
      if (responseSourcePath) fs.writeFileSync(responseSourcePath, axeResult.response_html, "utf-8");

      const executionSeconds = (Date.now() - itemStart) / 1000;

      results.push({
        url,
        status: "completed",
        execution_seconds: executionSeconds,
        html_metrics: axeResult.html_metrics,
        load_metadata: axeResult.load_metadata,
        screenshot_path: axeResult.screenshot_path,
        screenshot_mode: axeResult.screenshot_mode,
        acquisition: axeResult.acquisition,
        source_snapshot_path: sourceSnapshotPath,
        response_source_path: responseSourcePath,
        axe: {
          violations: axeResult.summary.violations,
          critical: axeResult.summary.critical,
          serious: axeResult.summary.serious,
          moderate: axeResult.summary.moderate,
          minor: axeResult.summary.minor,
          failed_rules: axeResult.summary.failed_rules,
          critical_rules: axeResult.summary.critical_rules,
          serious_rules: axeResult.summary.serious_rules,
          moderate_rules: axeResult.summary.moderate_rules,
          minor_rules: axeResult.summary.minor_rules,
          needs_review: axeResult.summary.needs_review,
          needs_review_rules: axeResult.summary.needs_review_rules,
          best_practice_issues: axeResult.summary.best_practice_issues,
          best_practice_rules: axeResult.summary.best_practice_rules,
          wcag_violations: axeResult.summary.wcag_violations,
          wcag_critical: axeResult.summary.wcag_critical,
          wcag_serious: axeResult.summary.wcag_serious,
          wcag_moderate: axeResult.summary.wcag_moderate,
          wcag_minor: axeResult.summary.wcag_minor,
          wcag_failed_rules: axeResult.summary.wcag_failed_rules,
          wcag_needs_review: axeResult.summary.wcag_needs_review,
          raw_path: axePath
        },
        lighthouse: {
          accessibility_score: lighthouseResult.summary.accessibility_score,
          raw_path: lighthousePath
        },

      });

    } catch (error) {
      results.push({
        url,
        status: "failed",
        ...require('./harness_evidence').captureFailure(error),
        execution_seconds: (Date.now() - itemStart) / 1000
      });
    }
  }

  const totalExecutionSeconds = (Date.now() - experimentStart) / 1000;

  res.json({
    experiment_id,
    status: "completed",
    environment: {...getEnvironmentMetadata(
      totalExecutionSeconds,
      false,
      axe_standard,
      true,
      runtime_config
    ),...(quality_policy.require_complete_evidence===true&&urls.every(url=>!url.startsWith('http://dataset-server:8080/'))?{
      lighthouse_mode:'snapshot',evaluator_concurrency:'Sequential native capture, Axe and Lighthouse snapshot in one acquired desktop document; isolated process supervision'
    }:{lighthouse_mode:'navigation'})},
    results
  });
});

app.listen(3000, "0.0.0.0", () => {
  console.log("Evaluator service running on port 3000");
});
