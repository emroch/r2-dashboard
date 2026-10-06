// Spike (#107) driver: one card per library, each drawing the same two specs.
// A library loads only when its card nears the viewport, and every card redraws
// from its spec on a theme change or a legend change.
(function () {
  "use strict";
  const S = window.Spike;
  const libs = { plot: window.SpikePlot, echarts: window.SpikeEcharts, plotly: window.SpikePlotly };
  const scatterSpec = S.view.components["delivery-vs-vin"], mapSpec = S.view.components["geo-orders"];
  const drawn = [];
  for (const card of document.querySelectorAll(".lib")) {
    const lib = libs[card.dataset.lib];
    const sc = card.querySelector(".scatter"), mp = card.querySelector(".map");
    let hidden = new Set();
    const draw = () => { lib.scatter(sc, scatterSpec, hidden); return lib.map(mp, mapSpec); };
    hidden = S.legend(card.querySelector(".legend"),
      scatterSpec.series.map((s) => ({ name: s.name, cls: S.catClass(s.color) })), () => lib.scatter(sc, scatterSpec, hidden));
    S.whenNear(card, async () => {
      const t0 = performance.now();
      try {
        await lib.ready();
        await draw();
        S.cost(card.querySelector(".cost"), lib.urls, t0);
        drawn.push(draw);
      } catch (e) {
        card.querySelector(".cost").textContent = "failed: " + e.message;
        console.error(e);
      }
    });
  }
  const btn = document.getElementById("spikeTheme");
  btn.addEventListener("click", () => {
    const root = document.documentElement;
    root.dataset.theme = root.dataset.theme === "dark" ? "light" : "dark";
    drawn.forEach((d) => d());
  });
  const wh = document.getElementById("spikeWhiskers");
  wh.checked = S.whiskersOn();
  wh.addEventListener("change", () => {
    const u = new URL(location.href);
    u.searchParams.set("whiskers", wh.checked ? "1" : "0");
    history.replaceState(null, "", u);
    drawn.forEach((d) => d());
  });
})();
