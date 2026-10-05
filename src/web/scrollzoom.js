// Scroll-wheel arbitration for the maps: zoom the map, but defer to the page.
//
// Plotly enables wheel-zoom on geo subplots by default, which means a wheel
// gesture over a map hijacks the page scroll — annoying when you were only
// scrolling past the section. The fix here is intent-based rather than a hard
// on/off: if the PAGE has scrolled in the last moment, the wheel belongs to that
// scroll and passes straight through; if the page is at rest, the gesture was
// aimed at the map and Plotly zooms as normal.
//
// Suppression works by listening in the CAPTURE phase and calling
// stopPropagation() before Plotly's own wheel handler runs, so Plotly never sees
// the event and never calls preventDefault() — leaving the browser to scroll the
// page. When we do want a zoom we do nothing at all and let Plotly handle it,
// including its own preventDefault, so a zoom never also scrolls the page.
(function () {
  // How long after a page scroll the wheel still counts as "part of that scroll".
  // Long enough to cover trackpad momentum between events, short enough that a
  // deliberate gesture right after scrolling still zooms.
  var QUIET_MS = 250;
  var lastScroll = 0;

  window.addEventListener('scroll', function () {
    lastScroll = Date.now();
  }, { passive: true });

  document.addEventListener('wheel', function (e) {
    // Only arbitrate over a map; every other plot keeps Plotly's defaults.
    var plot = e.target.closest && e.target.closest('.js-plotly-plot');
    if (!plot || !plot.querySelector('.geolayer .geo')) return;
    if (Date.now() - lastScroll < QUIET_MS) {
      // Mid-scroll: let the page keep moving and keep Plotly out of it.
      e.stopPropagation();
    }
  }, { capture: true });
})();
