(function(){try{
// Light or Dark if the reader chose one (theme.js saves it), else System: the
// OS preference. Set before first paint, so the page never flashes the wrong
// theme. The old toggle's key (r2theme) saved a theme on every click, so it is
// dropped rather than read: everyone starts on System once.
localStorage.removeItem('r2theme');
var t=localStorage.getItem('r2-theme');
if(t!=='dark'&&t!=='light'){t=(window.matchMedia&&
window.matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light';}
document.documentElement.setAttribute('data-theme',t);
}catch{/* best effort */}})();
