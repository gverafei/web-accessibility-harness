const crypto = require("crypto");

function safeFileName(url) {
  const readable = String(url)
    .replace(/^https?:\/\//, "")
    .replace(/[^a-zA-Z0-9]/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "")
    .slice(0, 60);
  const digest = crypto.createHash("sha256").update(String(url)).digest("hex").slice(0, 16);
  return `${readable || "page"}_${digest}`;
}

module.exports = { safeFileName };
