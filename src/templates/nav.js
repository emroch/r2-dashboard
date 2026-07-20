
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
