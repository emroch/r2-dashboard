// The light/dark theme toggle. head.js has already set data-theme before first
// paint (saved choice, else the OS preference); this wires the button, saves a
// change, keeps the browser's theme-color in step with the header, and tells the
// rest of the page through one event:
//
//   r2:themechange   on document, detail {theme: 'light' | 'dark'}. Fired once
//                    at load with the current theme, then on every toggle.
//
// Anything drawn by script listens for it and redraws from its own spec
// (docs/presentation.md, "Theming"); nothing is re-tinted by trace index.
(function(){
var root=document.documentElement;
function current(){return root.getAttribute('data-theme')==='dark'?'dark':'light';}
function apply(t){
 root.setAttribute('data-theme',t);
 var b=document.getElementById('themeToggle');
 // A glyph and a label (the label hides on the compact header, css/02-header.css).
 if(b){var dark=t==='dark';
  b.textContent=dark?'\u2600':'\u263e';
  var l=document.createElement('span');l.className='pill-label';
  l.textContent=dark?' Light':' Dark';b.appendChild(l);}
 // The tab bar / status bar tint (Safari, mobile browsers) follows the header.
 var m=document.getElementById('theme-color');
 var hdr=getComputedStyle(root).getPropertyValue('--header-bg').trim();
 if(m&&hdr)m.setAttribute('content',hdr);
 document.dispatchEvent(new CustomEvent('r2:themechange',{detail:{theme:t}}));
}
window.addEventListener('load',function(){
 apply(current());
 var b=document.getElementById('themeToggle');
 if(b)b.addEventListener('click',function(){
  var nt=current()==='dark'?'light':'dark';
  try{localStorage.setItem('r2theme',nt);}catch{/* best effort */}
  apply(nt);
 });
});
})();
