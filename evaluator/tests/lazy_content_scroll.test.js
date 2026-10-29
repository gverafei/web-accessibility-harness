const test = require('node:test');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { activateLazyContent } = require('../run_axe');

const policy = {
  lazy_load_scroll: true,
  max_scroll_steps: 4,
  scroll_step_px: 600,
  scroll_delay_ms: 100,
};

async function fixture(check) {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
    headless: true,
    args: ['--no-sandbox'],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await check(page);
  } finally {
    await browser.close();
  }
}

test('lazy exploration does not send zoom gestures to a non-scrolling application', async () => {
  await fixture(async page => {
    await page.setContent(`<style>html,body{margin:0;height:100%;overflow:hidden}</style>
      <main role="application" style="height:100%">Interactive map</main>
      <script>window.zoom=5;window.wheels=0;
        document.addEventListener('wheel',()=>{window.zoom--;window.wheels++});</script>`);
    const steps = await activateLazyContent(page, policy);
    assert.equal(steps, 0);
    assert.deepEqual(await page.evaluate(() => [window.zoom, window.wheels, scrollY]), [5, 0, 0]);
  });
});

test('lazy exploration still reaches document content and restores the top', async () => {
  await fixture(async page => {
    await page.setContent(`<style>body{margin:0;height:2500px}</style>
      <p>Source content</p><script>window.explored=false;
        addEventListener('scroll',()=>{if(scrollY>500)window.explored=true});</script>`);
    assert.ok(await activateLazyContent(page, policy) > 0);
    assert.equal(await page.evaluate(() => window.explored), true);
    assert.equal(await page.evaluate(() => scrollY), 0);
  });
});
