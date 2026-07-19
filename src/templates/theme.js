
(function(){
/*__CHROME_JS__*/
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
  try{window.Plotly.relayout(gd,up);}catch(e){}
  var idx=[],staridx=[];
  (gd.data||[]).forEach(function(tr,i){
   var lc=tr.marker&&tr.marker.line?tr.marker.line.color:null;
   if(typeof lc==='string'&&managed.indexOf(lc.toLowerCase())>=0)idx.push(i);
   if(tr.marker&&tr.marker.symbol==='star')staridx.push(i);
  });
  if(idx.length){try{window.Plotly.restyle(gd,{'marker.line.color':t.edge},idx);}catch(e){}}
  if(staridx.length){try{window.Plotly.restyle(gd,{'marker.color':t.star},staridx);}catch(e){}}
 });
}
function apply(t){
 document.documentElement.setAttribute('data-theme',t);
 var b=document.getElementById('themeToggle');
 if(b)b.textContent=(t==='dark'?'\u2600 Light':'\u263e Dark');
 themeCharts(t==='dark');
}
window.addEventListener('load',function(){
 apply(document.documentElement.getAttribute('data-theme')||'light');
 var b=document.getElementById('themeToggle');
 if(b)b.addEventListener('click',function(){
  var cur=document.documentElement.getAttribute('data-theme')==='dark'?'dark':'light';
  var nt=cur==='dark'?'light':'dark';
  try{localStorage.setItem('r2theme',nt);}catch(e){}
  apply(nt);
 });
});
})();
