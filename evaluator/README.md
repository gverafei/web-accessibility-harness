# Web Accessibility Harness evaluator

The internal service supplies three contracts: `/harness/capture` acquires bounded public-page evidence, `/harness/validate` performs independent HTML syntax validation, and `/evaluate` measures a common frozen local replay with Axe and Lighthouse. `/health` reports actual tool versions and source hashes. Campaign execution freezes this fingerprint and interrupts on drift. No endpoint is published to the host.

Captures retain response/rendered HTML, a viewport snapshot, attributed bounded resource bodies, HTTP status and acquisition limitations. Private addresses are blocked during capture; HTTP errors and verified interstitials remain explicit failures. Replayed pages use captured assets and a common CSP. Multiple captured CSP headers remain separate CDP response headers or an equivalent comma-separated policy list for route fulfillment. They cannot contain a newline inside one CDP header; all policies remain enforced. Unacquired interactions and server-side actions remain unverified. Capturing or evaluating a page does not establish preserved task semantics.

Selected acquired DOM states suspend inherited application initializers during frozen replay; new repair scripts remain executable. Media observations record source objects, buffered ranges and native dimensions without inferring playback. Browser child processes receive only browser-policy settings, excluding provider credentials.

Each browser audit executes in its own supervised Node process. Lighthouse has a 180-second outer deadline; Axe's deadline includes cleanup. Buffer overflow, tool errors and timeouts remain failures. The supervisor tracks owned Linux descendants by PID/start time, including detached Chromium, and closes only those processes. `init: true` reaps terminated orphans.

The image uses exact direct package versions and `npm ci` with its lockfile. Actual Chromium/Axe/Lighthouse/HTML-validator versions are evidence; changing them requires a new frozen comparison configuration. Rebuild after evaluator source or dependency changes.

Run in a disposable isolated container, mounting current source at `/workspace`:

```sh
docker build -t web-accessibility-harness-evaluator:test evaluator
docker run --rm --init --network none --tmpfs /results --tmpfs /data -e NODE_PATH=/evaluator/node_modules \
  -v "$PWD:/workspace:ro" -w /workspace/evaluator \
  web-accessibility-harness-evaluator:test sh -c 'node --test tests/*.test.js'
```

The local replay fixture runs actual browser auditors against synthetic HTML without network or paid calls. Process cleanup tests cover success, failure and timeout. These are software verification fixtures, not study observations.

## Frozen evidence boundary

Source replay preserves recorded resources, native controls, paused animation/media state and initialized DOM under versioned adapters. Evidence inspection uses inert DOM copies; unknown resources remain blocked. Media reproduction uses real observed bytes and decoder checks, never invented readiness. Limits and adapter versions live in executable modules and immutable capture metadata.

Compare capture/replay phase identities and audits on the same document. Drift, missing bodies, decoding errors and ambiguous identities stay explicit instrument diagnostics. Recovery uses recorded evidence and cannot grant new acquisitions. Technical browser regressions remain engineering checks; task success and complete accessibility require separate study evidence.

Visible-image settlement uses `visible_images.js` to respect CSS visibility, ancestor clipping and viewport intersection. It waits again when scrolling reveals a pending image; it does not rewrite media or authored loading attributes. Browser fixtures cover visibility, clipping, scroll restoration and native lazy loading.
