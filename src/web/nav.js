
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
