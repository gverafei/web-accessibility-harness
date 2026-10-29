const test = require("node:test");
const assert = require("node:assert/strict");

const { extractAccessibilityScore } = require("../run_lighthouse");

test("extracts and rounds a complete accessibility score", () => {
  assert.equal(extractAccessibilityScore({
    categories: { accessibility: { score: 0.934 } }
  }), 93);
});

test("rejects a Lighthouse runtime error instead of storing a partial success", () => {
  assert.throws(
    () => extractAccessibilityScore({
      categories: { accessibility: { score: null } },
      runtimeError: { message: "Status code: 403" }
    }),
    /Lighthouse incomplete result: Status code: 403/
  );
});

test("rejects a missing accessibility score", () => {
  assert.throws(() => extractAccessibilityScore({ categories: {} }), /incomplete result/);
});
