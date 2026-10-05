
// Re-tints the Plotly charts' chrome (text, gridlines, geo land, legend boxes,
// the managed edge grey) when the theme changes. Data colors are left alone.
(function(){
// The light/dark chart chrome from theme.yaml, which the build writes into the
// page as a JSON island (this file is a static asset, the same on every build).
var CHROME=JSON.parse(document.getElementById('chrome-data').textContent);
var LIGHT=CHROME.light,DARK=CHROME.dark;
function themeCharts(dark){
 if(!window.Plotly)return;
 var t=dark?DARK:LIGHT;
 document.querySelectorAll('.js-plotly-plot').forEach(function(gd){
  if(!gd.layout)return;
  var managed=[LIGHT.edge,DARK.edge];
  var up={'font.color':t.text,'paper_bgcolor':'rgba(0,0,0,0)',
          'plot_bgcolor':'rgba(0,0,0,0)'};
  Object.keys(gd.layout).forEach(function(k){
   if(/^xaxis|^yaxis/.test(k)){
    up[k+'.gridcolor']=t.grid;up[k+'.zerolinecolor']=t.grid;up[k+'.linecolor']=t.line;
   }else if(/^geo/.test(k)){
    up[k+'.bgcolor']='rgba(0,0,0,0)';up[k+'.landcolor']=t.land;
    up[k+'.subunitcolor']=t.sub;up[k+'.countrycolor']=t.country;
   }else if(/^legend/.test(k)){
    up[k+'.bgcolor']=t.legbg;up[k+'.bordercolor']=t.legbd;
    up[k+'.font.color']=t.text;up[k+'.title.font.color']=t.text;
   }
  });
  (gd.layout.shapes||[]).forEach(function(sh,i){
   var sc=sh.line&&sh.line.color?String(sh.line.color).toLowerCase():null;
   if(sc&&managed.indexOf(sc)>=0)up['shapes['+i+'].line.color']=t.edge;
  });
  (gd.layout.annotations||[]).forEach(function(an,i){
   var ac=an.font&&an.font.color?String(an.font.color).toLowerCase():null;
   if(ac&&managed.indexOf(ac)>=0)up['annotations['+i+'].font.color']=t.edge;
  });
  // Filter dropdowns/buttons keep a fixed light background + dark text (not
  // theme-swapped): their hover highlight is a fixed bright fill, so dark text
  // stays legible in both idle and hover states, in light or dark mode.
  try{window.Plotly.relayout(gd,up);}catch{/* best effort */}
  var idx=[],staridx=[],boxidx=[];
  (gd.data||[]).forEach(function(tr,i){
   var lc=tr.marker&&tr.marker.line?tr.marker.line.color:null;
   if(typeof lc==='string'&&managed.indexOf(lc.toLowerCase())>=0)idx.push(i);
   if(tr.marker&&tr.marker.symbol==='star')staridx.push(i);
   // Box outlines/whiskers carry their color on the TRACE's line, not
   // marker.line, so they need their own pass or they keep the light-theme
   // near-black and vanish against the dark card.
   var bl=tr.line?tr.line.color:null;
   if(tr.type==='box'&&typeof bl==='string'&&managed.indexOf(bl.toLowerCase())>=0)boxidx.push(i);
  });
  if(idx.length){try{window.Plotly.restyle(gd,{'marker.line.color':t.edge},idx);}catch{/* best effort */}}
  if(boxidx.length){try{window.Plotly.restyle(gd,{'line.color':t.edge},boxidx);}catch{/* best effort */}}
  if(staridx.length){try{window.Plotly.restyle(gd,{'marker.color':t.star},staridx);}catch{/* best effort */}}
 });
}
// The theme toggle (theme.js) announces every change, including the theme the
// page loaded in, as an r2:themechange event. The Plotly charts are baked in
// light colors, so each one re-tints its chrome here. This whole file goes away
// with the last Plotly chart (docs/presentation.md, #111).
document.addEventListener('r2:themechange',function(e){
 themeCharts(e.detail.theme==='dark');
});
})();
