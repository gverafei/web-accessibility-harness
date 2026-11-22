const { runAxe } = require("./run_axe");

async function main() {
  try {
    const { url, screenshotPath, options } = JSON.parse(process.argv[2]);
    const result = await runAxe(url, screenshotPath, options);
    process.stdout.write(JSON.stringify(result));
  } catch (error) {
    process.stderr.write(error?.stack || String(error));
    process.exitCode = 1;
  } finally {
    if (process.connected) process.disconnect();
  }
}

if (require.main === module) main();
