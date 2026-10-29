const assert = require("node:assert/strict");
const test = require("node:test");

const {
  AXE_PROFILES, acquisitionRejection, isLocalDatasetUrl, isMovedNotice, isSecurityChallenge, loadPolicy, summarizeAxeResults
} = require("../run_axe");

test("WCAG profiles are cumulative and default profile covers WCAG 2.2 AA", () => {
  assert.deepEqual(AXE_PROFILES.wcag22aa, [
    "wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"
  ]);
  assert.deepEqual(AXE_PROFILES.wcag20a, ["wcag2a"]);
  assert.equal(AXE_PROFILES.wcag22aa.includes("best-practice"), false);
});

test("dynamic-page policy enables lazy scrolling by default", () => {
  const previous = process.env.ENABLE_LAZY_LOAD_SCROLL;
  delete process.env.ENABLE_LAZY_LOAD_SCROLL;
  try {
    const policy = loadPolicy();
    assert.equal(policy.lazy_load_scroll, true);
    assert.equal(policy.interaction_activation, true);
    assert.equal(policy.scroll_delay_ms, 400);
    assert.equal(policy.page_settle_delay_ms, 2000);
    assert.equal(policy.axe_hard_timeout_ms, 240000);
    assert.equal(policy.dom_stability_window_ms, 1500);
  } finally {
    if (previous === undefined) delete process.env.ENABLE_LAZY_LOAD_SCROLL;
    else process.env.ENABLE_LAZY_LOAD_SCROLL = previous;
  }
});

test("dynamic-page policy reads explicit experiment settings", () => {
  const previous = process.env.SCROLL_STEP_PX;
  process.env.SCROLL_STEP_PX = "900";
  try {
    assert.equal(loadPolicy().scroll_step_px, 900);
  } finally {
    if (previous === undefined) delete process.env.SCROLL_STEP_PX;
    else process.env.SCROLL_STEP_PX = previous;
  }
});

test("web configuration overrides environment policy values", () => {
  const policy = loadPolicy({
    enable_lazy_load_scroll: "false",
    scroll_step_px: "420",
    page_settle_delay_ms: "750"
  });
  assert.equal(policy.lazy_load_scroll, false);
  assert.equal(policy.scroll_step_px, 420);
  assert.equal(policy.page_settle_delay_ms, 750);
});

test("best-practice issue instances are reported separately", () => {
  const summary = summarizeAxeResults({
    violations: [
      { impact: "serious", tags: ["wcag2aa"], nodes: [{}, {}] },
      { impact: "moderate", tags: ["best-practice"], nodes: [{}, {}, {}] }
    ],
    incomplete: [{ nodes: [{}] }]
  }, "wcag22aa", true, ["wcag22aa", "best-practice"]);

  assert.equal(summary.violations, 5);
  assert.equal(summary.best_practice_issues, 3);
  assert.equal(summary.best_practice_rules, 1);
  assert.equal(summary.needs_review, 1);
  assert.equal(summary.wcag_violations, 2);
  assert.equal(summary.wcag_serious, 2);
  assert.equal(summary.wcag_moderate, 0);
  assert.equal(summary.wcag_failed_rules, 1);
});

test("acquisition recognizes relocation notices and security challenges", () => {
  assert.equal(isMovedNotice("This site has moved to a new address"), true);
  assert.equal(isMovedNotice("Publisher home page"), false);
  assert.equal(isSecurityChallenge("https://example.org/", "Security Verification"), true);
  assert.equal(isSecurityChallenge("https://example.org/captcha/check", ""), true);
  assert.equal(isSecurityChallenge("https://reddit.com/?js_challenge=1&jsc_token=x", ""), true);
  assert.equal(isSecurityChallenge("https://example.org/research", "Research portal"), false);
  assert.equal(isLocalDatasetUrl("http://dataset-server:8080/key/page.html"), true);
  assert.equal(isSecurityChallenge(
    "http://dataset-server:8080/key/security-verification.html",
    "Security Verification and access denied"
  ), false);
});

test("acquisition rejects non-homepage responses using explicit WebAIM-style quality rules", () => {
  assert.match(acquisitionRejection({ dom_nodes: 9, visible_text_length: 100 }, "Page"), /fewer than 10/);
  assert.match(acquisitionRejection({ dom_nodes: 10, visible_text_length: 2 }, ""), /blank or minimal/);
  assert.match(acquisitionRejection({ dom_nodes: 100, visible_text_length: 1000, same_domain_links: 5001 }, "Page"), /5,000/);
  assert.equal(acquisitionRejection({ dom_nodes: 10, visible_text_length: 100, same_domain_links: 4 }, "Page"), null);
});
