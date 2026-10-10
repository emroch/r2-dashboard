
(function(){
 var el=document.documentElement;
 // The sidebar's tiers (css/03-sidebar.css): under 768px an overlay the menu
 // button opens (nav-shown); 768-1071px shown, and the button hides it
 // (nav-hidden); 1072px+ always shown. Crossing a tier resets to its default.
 var narrowQ=window.matchMedia('(width < 768px)');
 var midQ=window.matchMedia('(768px <= width < 1072px)');
 function close(){el.classList.remove('nav-shown');}
 function reset(){el.classList.remove('nav-shown','nav-hidden');}
 narrowQ.addEventListener('change',reset);
 midQ.addEventListener('change',reset);
 var tgl=document.getElementById('navToggle');
 if(tgl)tgl.addEventListener('click',function(){
  el.classList.toggle(narrowQ.matches?'nav-shown':'nav-hidden');
 });
 var bd=document.getElementById('navBackdrop');
 if(bd)bd.addEventListener('click',close);
 var links={};
 document.querySelectorAll('.sidebar a[data-sec]').forEach(function(a){
  links[a.getAttribute('data-sec')]=a;
  a.addEventListener('click',function(){if(narrowQ.matches)close();});
 });
 var secs=document.querySelectorAll('section[id]');
 if(secs.length&&'IntersectionObserver' in window){
  var obs=new IntersectionObserver(function(entries){
   entries.forEach(function(e){
    if(e.isIntersecting)for(var k in links)links[k].classList.toggle('active',k===e.target.id);
   });
  },{rootMargin:'-45% 0px -50% 0px',threshold:0});
  secs.forEach(function(s){obs.observe(s);});
 }
 // The header's height is dynamic (the title and disclaimer wrap), so it is
 // measured here. On narrow screens (css/02-header.css, under 768px) the header
 // sticks with a negative top: the title and disclaimer scroll away and only its
 // last row (menu + action pills) stays pinned, a compact bar. --header-tuck is
 // how far it tucks up, --header-pin the pinned bar's height (anchor offsets),
 // and --header-h how much of it shows right now (the sidebar sits below that).
 var hdr=document.querySelector('.topbar');
 var last=hdr&&hdr.querySelector('.topbar-actions');
 function setHeaderH(){
  if(!hdr)return;
  var narrow=narrowQ.matches;
  // Tuck to the row gap above the last row, so nothing of the row before peeks
  // out; the gap stands in for the bar's top padding.
  var gap=parseFloat(getComputedStyle(hdr).rowGap)||0;
  var tuck=narrow&&last?Math.max(0,last.offsetTop-gap):0;
  el.style.setProperty('--header-tuck',tuck+'px');
  el.style.setProperty('--header-pin',(hdr.offsetHeight-tuck)+'px');
  showing();
 }
 var queued=false;
 function showing(){
  queued=false;
  var r=hdr.getBoundingClientRect();
  el.style.setProperty('--header-h',Math.max(0,Math.round(r.bottom))+'px');
  // Fully tucked: the compact bar, whose pills drop to their glyphs.
  var tuck=parseFloat(el.style.getPropertyValue('--header-tuck'))||0;
  el.classList.toggle('header-tucked',tuck>0&&r.top<=-tuck+0.5);
 }
 setHeaderH();
 // Re-measure whenever the header re-flows (a resize, the breakpoint, the
 // title wrapping, the pills changing width), not on window resize alone,
 // which can fire before the new layout is in.
 if(hdr&&'ResizeObserver' in window)new ResizeObserver(setHeaderH).observe(hdr);
 narrowQ.addEventListener('change',setHeaderH);
 window.addEventListener('resize',setHeaderH);
 window.addEventListener('load',setHeaderH);
 window.addEventListener('scroll',function(){
  if(hdr&&!queued){queued=true;requestAnimationFrame(showing);}
 },{passive:true});
})();

(function(){
 // The header menus (Report issue, Theme) are <details>, so they open and close
 // without any JS. What <details> doesn't do is dismiss on an outside click or
 // Escape, which is what makes one feel like a menu rather than a stuck-open
 // panel; opening one closes the other, as a click outside it.
 var menus=document.querySelectorAll('details.hdrmenu');
 document.addEventListener('click',function(e){
  menus.forEach(function(d){if(d.open&&!d.contains(e.target))d.open=false;});
 });
 document.addEventListener('keydown',function(e){
  if(e.key!=='Escape')return;
  menus.forEach(function(d){if(d.open){d.open=false;
   var s=d.querySelector('summary'); if(s)s.focus();}});
 });
 // Picking an item closes its menu: a report link opens a new tab, and the menu
 // shouldn't still be open on returning (#46); a theme applies at once.
 menus.forEach(function(d){
  d.querySelectorAll('.hdrpop a, .hdrpop button').forEach(function(a){
   a.addEventListener('click',function(){d.open=false;});
  });
 });
})();

(function(){
 // Keep the reading position through a re-layout. When the content column
 // changes width (a window resize, the sidebar sliding), text above the fold
 // re-wraps and changes height, which would push what the reader was looking
 // at up or down. So: remember the first block under the header and how far
 // below the header it sits, and after every re-layout scroll just enough to
 // put it back. The anchor is re-picked whenever the reader scrolls, never in
 // response to our own correction. Browsers with native scroll anchoring
 // (overflow-anchor) already do some of this; the correction then finds
 // nothing to do.
 var main=document.querySelector('.main');
 var hdr=document.querySelector('.topbar');
 if(!main||!('ResizeObserver' in window))return;
 var anchor=null, offset=0, ours=false;
 // Blocks worth holding on to: headings, paragraphs, rows, chart frames; not a
 // text span, or an SVG mark that a redraw replaces.
 var BLOCKS='h2,h3,p,li,tr,figure,.r2c,.chart-plot,.tr-row,.mx-row,.qa-cat';
 function top(){return hdr?Math.max(0,hdr.getBoundingClientRect().bottom):0;}
 // The anchor is the first block, in reading order, that reaches below the
 // header: the one being read (partly scrolled under the header) or, between
 // cards, the next one down. Found by walking the cards rather than probing a
 // point, which can land in a gap that belongs to no block.
 function pick(){
  var line=top(); anchor=null;
  var cards=main.querySelectorAll('section');
  for(var i=0;i<cards.length&&!anchor;i++){
   if(cards[i].getBoundingClientRect().bottom<=line)continue;
   var bs=cards[i].querySelectorAll(BLOCKS);
   for(var j=0;j<bs.length;j++){
    if(bs[j].closest('svg'))continue;
    var r=bs[j].getBoundingClientRect();
    if(r.height&&r.bottom>line){anchor=bs[j];break;}
   }
   if(!anchor)anchor=cards[i];
  }
  if(anchor)offset=anchor.getBoundingClientRect().top-line;
 }
 function restore(){
  if(!anchor||!anchor.isConnected)return;
  var d=anchor.getBoundingClientRect().top-top()-offset;
  if(Math.abs(d)<0.5)return;
  ours=true;
  window.scrollTo({top:window.scrollY+d,behavior:'instant'});
 }
 // Re-pick at most once a frame while the reader scrolls.
 var queued=false;
 window.addEventListener('scroll',function(){
  if(ours){ours=false;return;}
  if(!queued){queued=true;requestAnimationFrame(function(){queued=false;pick();});}
 },{passive:true});
 // Every re-layout of the column restores the anchor: frame by frame while
 // the sidebar slides, each step while a window is dragged, and again when
 // the charts redraw at their new width (taller or shorter) a moment later.
 // A change below the anchor doesn't move it, so restoring then is a no-op.
 new ResizeObserver(restore).observe(main);
 // The sidebar slide moves the column without resizing the window: hold the
 // anchor through each frame of it.
 var raf=0;
 function follow(until){
  cancelAnimationFrame(raf);
  (function step(){restore();if(performance.now()<until)raf=requestAnimationFrame(step);})();
 }
 var tgl=document.getElementById('navToggle');
 if(tgl)tgl.addEventListener('click',function(){if(!anchor)pick();follow(performance.now()+600);});
 pick();
})();

(function(){
 // Localize the server-rendered <time data-r2time> stamps to the viewer's own
 // timezone (the datetime attr carries the absolute instant); falls back to the
 // build-timezone text if this doesn't run.
 var tzf; try{tzf=new Intl.DateTimeFormat(undefined,{timeZoneName:'short'});}catch{/* best effort */}
 function pad(n){return (n<10?'0':'')+n;}
 document.querySelectorAll('time[data-r2time]').forEach(function(t){
  var d=new Date(t.getAttribute('datetime'));
  if(isNaN(d.getTime()))return;
  var tz='';
  if(tzf){var p=tzf.formatToParts(d).filter(function(x){return x.type==='timeZoneName';});
   if(p.length)tz=' '+p[0].value;}
  t.textContent=d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+
   ' '+pad(d.getHours())+':'+pad(d.getMinutes())+tz;
 });
})();
