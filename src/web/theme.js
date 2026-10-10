// The theme menu: Light, Dark or System (follow the OS). head.js has already set
// data-theme before first paint (a saved Light or Dark, else the OS preference);
// this wires the menu, saves a choice (System saves none), follows the OS while
// System is chosen, keeps the browser's theme-color in step with the header, and
// tells the rest of the page through one event:
//
//   r2:themechange   on document, detail {theme: 'light' | 'dark'}. Fired once
//                    at load with the current theme, then whenever it changes.
//
// Anything drawn by script listens for it and redraws from its own spec
// (docs/presentation.md, "Theming"); nothing is re-tinted by trace index.
(function(){
var root=document.documentElement;
var os=window.matchMedia('(prefers-color-scheme: dark)');
function saved(){
 try{var t=localStorage.getItem('r2theme');}catch{t=null;}
 return t==='light'||t==='dark'?t:'system';
}
var mode=saved(), shown=null;
function apply(){
 var t=mode==='system'?(os.matches?'dark':'light'):mode;
 root.setAttribute('data-theme',t);
 // The pill shows the theme in use; the menu marks the choice.
 var g=document.querySelector('#themeMenu .theme-glyph');
 if(g)g.textContent=t==='dark'?'\u263e':'\u2600';
 document.querySelectorAll('#themeMenu [data-mode]').forEach(function(b){
  b.setAttribute('aria-pressed',String(b.getAttribute('data-mode')===mode));
 });
 // The tab bar / status bar tint (Safari, mobile browsers) follows the header.
 var m=document.getElementById('theme-color');
 var hdr=getComputedStyle(root).getPropertyValue('--header-bg').trim();
 if(m&&hdr)m.setAttribute('content',hdr);
 if(t!==shown){shown=t;
  document.dispatchEvent(new CustomEvent('r2:themechange',{detail:{theme:t}}));}
}
os.addEventListener('change',function(){if(mode==='system')apply();});
window.addEventListener('load',function(){
 apply();
 document.querySelectorAll('#themeMenu [data-mode]').forEach(function(b){
  b.addEventListener('click',function(){
   mode=b.getAttribute('data-mode');
   try{if(mode==='system')localStorage.removeItem('r2theme');
       else localStorage.setItem('r2theme',mode);}catch{/* best effort */}
   apply();
  });
 });
});
})();
