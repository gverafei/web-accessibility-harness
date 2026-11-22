function extractAccessibilityScore(lhr) {
  const score = lhr?.categories?.accessibility?.score;
  if (lhr?.runtimeError || !Number.isFinite(score)) {
    const detail = lhr?.runtimeError?.message || "no accessibility score was produced";
    throw new Error(`Lighthouse incomplete result: ${detail}`);
  }
  return Math.round(score * 100);
}

module.exports = { extractAccessibilityScore };
