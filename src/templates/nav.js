
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
 // Tuck the sidebar/backdrop below the full-width header (its height is dynamic).
 function setHeaderH(){var h=document.querySelector('.topbar');
  if(h)el.style.setProperty('--header-h',h.offsetHeight+'px');}
 setHeaderH();
 window.addEventListener('resize',setHeaderH);
 window.addEventListener('load',setHeaderH);
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
})();

(function(){
 // Localize the server-rendered <time data-r2time> stamps to the viewer's own
 // timezone (the datetime attr carries the absolute instant); falls back to the
 // build-timezone text if this doesn't run.
 var tzf; try{tzf=new Intl.DateTimeFormat(undefined,{timeZoneName:'short'});}catch(e){}
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
