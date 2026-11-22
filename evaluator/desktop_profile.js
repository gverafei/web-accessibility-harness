'use strict';
const VERSION='desktop-1440x1000-v2';
const viewport=Object.freeze({width:1440,height:1000});
function contextOptions(){return {viewport:{...viewport},isMobile:false,deviceScaleFactor:1};}
function lighthouseFlags(snapshot=false){return {formFactor:'desktop',emulatedUserAgent:false,disableFullPageScreenshot:true,
 screenEmulation:snapshot?{disabled:true}:{mobile:false,width:1440,height:1000,deviceScaleFactor:1,disabled:false}};}
module.exports={VERSION,viewport,contextOptions,lighthouseFlags};
