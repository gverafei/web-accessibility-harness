'use strict';
const VERSION='native-reference-state-v12';
async function capture(page,collector,screenshotPath,policy=require('./run_axe').loadPolicy()){
 await require('./frozen_media').settle(page);
 const initialPreparation=await require('./desktop_capture').prepare(page);
 // Body retrieval can outlast a carousel interval. Finish that work before
 // choosing the acquired reference, never between its HTML and visible data.
 let resources=await collector.finish({close:false});
 const carouselState=await require('./carousel_measurement').prepare(page);
 // Segment traversal can activate images after the initial lazy-resource wait.
 // Decode those actual resources before freezing the reference, without a new navigation.
 await require('./run_axe').settleLazyResources(page,policy);
 await require('./frozen_media').settle(page);
 const measurementState=await require('./measurement_state').freeze(page);
 // Authored fetch promises can append a lazy image after the initial traversal.
 // Traverse the final frozen document too; built-in image loading is retained.
 const frozenPreparation=await require('./desktop_capture').prepare(page);
 await require('./run_axe').settleLazyResources(page,policy);
 const stability=await require('./run_axe').waitForDomStability(page,policy);
 if(!stability.stable)throw Error('Native reference did not stabilize after resource settlement');
 // Freezing timers/observers cannot cancel a fetch promise already in flight.
 // Keep collecting resources and rebuild the entire reference if that promise
 // changes the document. Never pair earlier HTML with a later screenshot.
 for(let attempt=1;attempt<=3;attempt++){
  const html=await page.content();
  const native_control_reference=await require('./native_control_state').capture(page);
  const visible={...await require('./replay_admission').visibleEvidence(page),animation_reference:await require('./frozen_animation_state').capture(page)};
  const screenshot=await require('./desktop_capture').capture(page,screenshotPath);
  resources=await collector.finish({close:false});
  if(await page.content()===html){
   resources=await collector.finish();
   if(await page.content()===html&&JSON.stringify((await require('./native_control_state').capture(page)).records)===JSON.stringify(native_control_reference.records)){
    const mse_buffer_reference=await require('./observed_mse_buffers').reference(page,visible);
    const worker_media_reference=await require('./observed_worker_media').reference(page,visible);
    if(JSON.stringify((await require('./native_control_state').capture(page)).records)!==JSON.stringify(native_control_reference.records))continue;
    const derivedBytes=mse_buffer_reference.total_bytes+worker_media_reference.total_bytes;
    if(derivedBytes){if(!collector.reserveDerived)throw Error('MSE derived resource accounting unavailable');collector.reserveDerived(derivedBytes);}
    resources={...resources,derived_mse_bytes:mse_buffer_reference.total_bytes,derived_worker_media_bytes:worker_media_reference.total_bytes,total_resource_evidence_bytes:collector.reservedBytes?collector.reservedBytes():resources.bytes||0};
    if(await page.content()!==html)throw Error('Native document changed while recording MSE evidence');
    return {version:VERSION,resources,mse_buffer_reference,worker_media_reference,native_control_reference,html,visible,screenshot,media_pause:await require('./native_media_pause').snapshot(page),measurement_state:measurementState,carousel_state:carouselState,stabilization_attempts:attempt,resource_stability:stability,segment_preparation:{initial:initialPreparation,frozen:frozenPreparation}};
   }
   // The DOM can remain byte-identical while native values change.
   // Rebuild the entire reference, including its screenshot, in that case.
   if(await page.content()===html)continue;
   break;
  }
  // Keep the actual last source delta for technical diagnosis; a failed
  // stabilization remains invalid evidence and is never admitted here.
  require('node:fs').writeFileSync(screenshotPath+'.instability-dom.json',JSON.stringify({version:VERSION,attempt,before:html,after:await page.content()}));
 }
 throw Error('Native reference changed during desktop capture after bounded stabilization');
}
module.exports={VERSION,capture};
