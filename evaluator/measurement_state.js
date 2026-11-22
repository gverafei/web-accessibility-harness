'use strict';
const VERSION='frozen-measurement-state-v11';
async function install(page){
 await page.addInitScript(()=>{
  const native={setTimeout:window.setTimeout.bind(window),setInterval:window.setInterval.bind(window),requestAnimationFrame:window.requestAnimationFrame.bind(window)};
  const timeouts=new Set(),intervals=new Set(),frames=new Set(),observers=new Set(),resizeObservers=new Set(),mutationObservers=new Set();
  let measurementFrozen=false;
  const liveTransports=new Set(),messageChannels=new Set();
  // Framework schedulers use MessageChannel independently of timers and workers.
  // Keep native ports open, gating callbacks only in the measured frozen state.
  const NativeChannel=window.MessageChannel;
  if(NativeChannel)window.MessageChannel=class extends NativeChannel{
   constructor(...args){super(...args);messageChannels.add(this);
    for(const port of [this.port1,this.port2])for(const type of ['message','messageerror'])
     port.addEventListener(type,event=>{if(measurementFrozen)event.stopImmediatePropagation();},true);
   }
  };
  // Live feeds can update market prices after timers/observers are paused.
  // Gate their events before authored handlers, keeping the acquired values
  // and open transport intact rather than closing it and triggering teardown.
  for(const name of ['WebSocket','EventSource','Worker']){
   const Original=window[name];if(!Original)continue;
   window[name]=class extends Original{
    constructor(...args){super(...args);liveTransports.add(this);
     for(const type of ['message','error','open','close'])this.addEventListener(type,event=>{if(measurementFrozen)event.stopImmediatePropagation();},true);
    }
   };
  }
  // Install before authored listeners. Non-bubbling Window events execute
  // target listeners in registration order, so a late gate cannot stop them.
  const installGates=()=>{for(const type of ['scroll','resize','mouseover','mouseout','mouseenter','mouseleave','pointerover','pointerout','pointerenter','pointerleave','mousemove','pointermove'])window.addEventListener(type,event=>{if(measurementFrozen)event.stopImmediatePropagation();},true);};
  installGates();
  // document.open clears Window event listeners before injected scripts run.
  // Reinstall the gates immediately after opening, before document.write.
  const open=document.open;
  document.open=function(...args){const result=Reflect.apply(open,this,args);if(args.length<3)installGates();return result;};
  const focus=HTMLElement.prototype.focus;
  HTMLElement.prototype.focus=function(options){
   // Auditors may temporarily focus descendants and restore focus while
   // leaving an overflow carousel scrolled. Preserve focus semantics but
   // prevent this implicit movement of the acquired measurement viewport.
   return Reflect.apply(focus,this,[measurementFrozen?{...(options&&typeof options==='object'?options:{}),preventScroll:true}:options]);
  };
  window.setTimeout=(callback,delay,...args)=>{let id;id=native.setTimeout(()=>{timeouts.delete(id);if(typeof callback==='function')callback(...args);else (0,eval)(callback);},delay);timeouts.add(id);return id;};
  window.setInterval=(callback,delay,...args)=>{const id=native.setInterval(callback,delay,...args);intervals.add(id);return id;};
  window.requestAnimationFrame=callback=>{let id;id=native.requestAnimationFrame(time=>{frames.delete(id);callback(time);});frames.add(id);return id;};
  const Intersection=window.IntersectionObserver;
  if(Intersection)window.IntersectionObserver=class extends Intersection{constructor(callback,...args){super(typeof callback==='function'?function(...values){if(!measurementFrozen)Reflect.apply(callback,this,values);}:callback,...args);observers.add(this);}};
  const Resize=window.ResizeObserver,Mutation=window.MutationObserver;
  if(Resize)window.ResizeObserver=class extends Resize{constructor(callback,...args){super(typeof callback==='function'?function(...values){if(!measurementFrozen)Reflect.apply(callback,this,values);}:callback,...args);resizeObservers.add(this);}};
  if(Mutation)window.MutationObserver=class extends Mutation{constructor(callback,...args){super(typeof callback==='function'?function(...values){if(!measurementFrozen)Reflect.apply(callback,this,values);}:callback,...args);mutationObservers.add(this);}};
  Object.defineProperty(window,'__harnessFreezeMeasurement',{value:()=>{
   measurementFrozen=true;
   const result={timeouts:timeouts.size,intervals:intervals.size,animation_frames:frames.size,intersection_observers:observers.size,resize_observers:resizeObservers.size,mutation_observers:mutationObservers.size,message_channels:messageChannels.size,message_channel_callbacks_suspended:true,live_transports:liveTransports.size,live_transport_callbacks_suspended:true,implicit_focus_scrolling_suspended:true};
   for(const id of timeouts)clearTimeout(id);for(const id of intervals)clearInterval(id);for(const id of frames)cancelAnimationFrame(id);for(const observer of [...observers,...resizeObservers,...mutationObservers])observer.disconnect();
   Object.assign(window,native);
   // Keep observer gates installed: a pending hydration promise can construct
   // new observers after the acquired ones were disconnected.
   // Measurement scrolling documents an already acquired state; it must not
   // trigger navigation hiding, autoplay or newly initialized lazy widgets.
   // Offscreen content-visibility regions can create CSS animations only when
   // the measurement scroll reveals them. Pause those future animations too.
   const style=document.createElement('style');style.dataset.harnessMeasurementFreeze='v3';
   style.textContent='*,*::before,*::after{animation-play-state:paused!important;transition-property:none!important;}';
   (document.head||document.documentElement).append(style);
   const animations=document.getAnimations();for(const animation of animations)animation.pause();
   // SVG SMIL timelines are independent of timers and the Web Animations API.
   // Pause their acquired time without deleting authored animation elements.
   const svgTimelines=[...document.querySelectorAll('svg')].filter(svg=>typeof svg.pauseAnimations==='function');
   for(const svg of svgTimelines)svg.pauseAnimations();
   const animate=Element.prototype.animate;
   Element.prototype.animate=function(...args){const animation=animate.apply(this,args);animation.pause();return animation;};
   return {...result,animations:animations.length,svg_animation_timelines:svgTimelines.length,svg_animations_suspended:true,future_animations_suspended:true,scroll_callbacks_suspended:true,resize_callbacks_suspended:true,hover_callbacks_suspended:true};
  },writable:false,configurable:false});
 });
}
async function freeze(page){
 // Measurement scrolling must not create hover states under the browser pointer.
 await page.mouse.move(-1,-1);
 const frozen=await page.evaluate(()=>window.__harnessFreezeMeasurement());
 const settled=await page.evaluate(async()=>{
  // Resolve pending compositor pauses before recording the first phase. Reading
  // offscreen styles also initializes content-visibility animation timelines.
  for(const element of document.querySelectorAll('*')){element.getBoundingClientRect();getComputedStyle(element).opacity;}
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  const animations=document.getAnimations();for(const animation of animations)animation.pause();
  // An inactive ScrollTimeline can leave pause().ready pending forever.
  // Bound that compositor wait; subsequent document/paint phase checks still
  // reject drift. Never claim that an unresolved pause has settled.
  let timer;
  const resolved=await Promise.race([
   Promise.all(animations.map(animation=>animation.ready.catch(()=>{}))).then(()=>true),
   new Promise(resolve=>timer=setTimeout(()=>resolve(false),1000))
  ]);clearTimeout(timer);
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  return {animation_pause_settled:resolved&&animations.every(a=>!a.pending),
   animation_pause_wait_ms:1000,pending_animation_pauses:animations.filter(a=>a.pending).length};
 });
 return {version:VERSION,...frozen,...settled};
}
module.exports={VERSION,install,freeze};
