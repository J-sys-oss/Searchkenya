// Real-time dashboard refresh: polls /api/stats every 5 seconds (no inline script, CSP-safe).
(function () {
  // Category bars on the report page: widths are applied from data-pct because the
  // Content-Security-Policy forbids inline style attributes.
  var bars = document.querySelectorAll(".bar span[data-pct]");
  for (var i = 0; i < bars.length; i++) bars[i].style.width = bars[i].getAttribute("data-pct") + "%";
  var box = document.getElementById("live");
  if (!box) return;
  function set(id, v) { var e = document.getElementById(id); if (e) e.textContent = v; }
  function tick() {
    fetch("/api/stats", {credentials: "same-origin"}).then(function (r) {
      return r.ok ? r.json() : null;
    }).then(function (s) {
      if (!s) return;
      set("v-total", s.total_crawled.toLocaleString());
      set("v-pending", s.pending.toLocaleString());
      set("v-disc", s.open_discrepancies.toLocaleString());
      set("v-fresh", s.freshness + "%");
      set("v-updated", new Date().toLocaleTimeString());
    }).catch(function () {});
  }
  setInterval(tick, 5000);
})();
