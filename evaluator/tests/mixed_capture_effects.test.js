const {test} = require('node:test');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const effects = require('../frozen_animation_state');

test('completed label reveal settles while an observed background effect retains its recorded time', async () => {
    const browser = await chromium.launch({executablePath:process.env.CHROMIUM_PATH || '/usr/bin/chromium',
        headless:true,args:['--no-sandbox']});
    try {
        const page = await browser.newPage();
        const pause = '<style data-harness-measurement-freeze="v3">*,*::before,*::after{animation-play-state:paused!important;transition-property:none!important;}</style>';
        const markup = `<html><head><style>
            @keyframes zoom{from{transform:scale(1)}to{transform:scale(1.05)}}
            @keyframes unblur{from{filter:blur(8px)}to{filter:blur(0)}}
            #background{animation:zoom 10s linear infinite}
            button{animation:unblur 80ms linear}
            </style></head><body><div id="background">Saved picture</div><button>Leer más</button></body></html>`;
        await page.setContent(markup);
        await page.waitForTimeout(160);
        await page.evaluate(() => {const a=document.querySelector('#background').getAnimations()[0];a.pause();a.currentTime=2500;});
        const reference = await effects.capture(page);
        assert.equal(reference.length,1);
        assert.equal(reference[0].time,2500);
        // The serialized audit-only pause causes the demonstrated label loss.
        await page.setContent(markup.replace('</head>',pause+'</head>'));
        assert.equal(await page.locator('button').evaluate(n=>getComputedStyle(n).filter),'blur(8px)');
        // Prepared copies omit only that known audit rule. Active effects are
        // restored individually, while completed effects can finish normally.
        await page.setContent(markup);
        assert.equal((await effects.restore(page,reference)).results[0].status,'restored');
        await page.waitForTimeout(160);
        assert.equal(await page.locator('button').evaluate(n=>getComputedStyle(n).filter),'none');
        assert.equal((await effects.capture(page))[0].time,2500);
        assert.equal(await page.getByRole('button').textContent(),'Leer más');
        await page.close();
    } finally { await browser.close(); }
});
