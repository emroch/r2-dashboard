
(function(){
 var el=document.documentElement;
 function close(){el.classList.remove('nav-shown');}
 var tgl=document.getElementById('navToggle');
 if(tgl)tgl.addEventListener('click',function(){el.classList.toggle('nav-shown');});
 var bd=document.getElementById('navBackdrop');
 if(bd)bd.addEventListener('click',close);
 var links={};
 document.querySelectorAll('.sidebar a[data-sec]').forEach(function(a){
  links[a.getAttribute('data-sec')]=a;
  a.addEventListener('click',function(){if(window.innerWidth<=900)close();});
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
 // measured here. On narrow screens (css/02-header.css, max-width 820px) the header
 // sticks with a negative top: the title and disclaimer scroll away and only its
 // last row (menu + action pills) stays pinned, a compact bar. --header-tuck is
 // how far it tucks up, --header-pin the pinned bar's height (anchor offsets),
 // and --header-h how much of it shows right now (the sidebar sits below that).
 var hdr=document.querySelector('.topbar');
 var last=hdr&&hdr.querySelector('.topbar-actions');
 function setHeaderH(){
  if(!hdr)return;
  var narrow=window.matchMedia('(max-width:820px)').matches;
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
  el.style.setProperty('--header-h',Math.max(0,Math.round(hdr.getBoundingClientRect().bottom))+'px');
 }
 setHeaderH();
 window.addEventListener('resize',setHeaderH);
 window.addEventListener('load',setHeaderH);
 window.addEventListener('scroll',function(){
  if(hdr&&!queued){queued=true;requestAnimationFrame(showing);}
 },{passive:true});
})();

(function(){
 // The report menu is a <details>, so it opens and closes without any JS. What
 // <details> doesn't do is dismiss on an outside click or Escape, which is what
 // makes it feel like a menu rather than a stuck-open panel.
 var d=document.getElementById('reportMenu');
 if(!d)return;
 document.addEventListener('click',function(e){
  if(d.open&&!d.contains(e.target))d.open=false;
 });
 document.addEventListener('keydown',function(e){
  if(e.key==='Escape'&&d.open){d.open=false;
   var s=d.querySelector('summary'); if(s)s.focus();}
 });
 // Picking one of its links opens a new tab; close the menu behind it, so it
 // isn't still open on returning to the dashboard (#46).
 d.querySelectorAll('.reportpop a').forEach(function(a){
  a.addEventListener('click',function(){d.open=false;});
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
