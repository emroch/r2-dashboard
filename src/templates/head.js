
(function(){try{var t=localStorage.getItem('r2theme');
if(t!=='dark'&&t!=='light'){t=(window.matchMedia&&
window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';}
document.documentElement.setAttribute('data-theme',t);
if(window.innerWidth>900)document.documentElement.classList.add('nav-shown');
}catch(e){}})();
