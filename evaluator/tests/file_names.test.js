const test = require("node:test");
const assert = require("node:assert/strict");
const { safeFileName } = require("../file_names");

test("long URLs with a shared prefix have distinct bounded names", () => {
  const first = safeFileName("http://dataset-server:8080/key/original/act-rules_github_io_rules_047fe0.html");
  const second = safeFileName("http://dataset-server:8080/key/original/act-rules_github_io_rules_5b7ae0.html");
  assert.notEqual(first, second);
  assert.ok(first.length <= 77);
  assert.match(first, /_[a-f0-9]{16}$/);
});

test("the same URL always receives the same evidence name", () => {
  const url = "https://example.org/a long path";
  assert.equal(safeFileName(url), safeFileName(url));
});
