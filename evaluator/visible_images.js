'use strict';
function visibleImagesSettled() {
  function visible(image) {
    if (!(image.currentSrc || image.getAttribute('src') || image.getAttribute('srcset'))) return false;
    if (!image.checkVisibility({checkOpacity:true,checkVisibilityCSS:true,contentVisibilityAuto:true})) return false;
    const rect=image.getBoundingClientRect();
    let left=Math.max(0,rect.left), right=Math.min(innerWidth,rect.right);
    let top=Math.max(0,rect.top), bottom=Math.min(innerHeight,rect.bottom);
    for(let parent=image.parentElement;parent;parent=parent.parentElement){
      const style=getComputedStyle(parent), box=parent.getBoundingClientRect();
      const scaleX=parent.offsetWidth ? box.width/parent.offsetWidth : 1;
      const scaleY=parent.offsetHeight ? box.height/parent.offsetHeight : 1;
      if(['hidden','clip','auto','scroll'].includes(style.overflowX)){
        left=Math.max(left,box.left+parent.clientLeft*scaleX);right=Math.min(right,box.left+(parent.clientLeft+parent.clientWidth)*scaleX);
      }
      if(['hidden','clip','auto','scroll'].includes(style.overflowY)){
        top=Math.max(top,box.top+parent.clientTop*scaleY);bottom=Math.min(bottom,box.top+(parent.clientTop+parent.clientHeight)*scaleY);
      }
    }
    return right>left && bottom>top;
  }
  return [...document.images].filter(visible).every(image=>image.complete);
}
module.exports={visibleImagesSettled};
