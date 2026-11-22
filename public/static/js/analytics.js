// Analytics charts (Spec 04). Reads the JSON in #analytics-data and draws up to 4 Chart.js charts.
// Flask renders every number, label, table and URL; this file only draws. Money arrives as strings.
(function () {
  "use strict";

  var dataEl = document.getElementById("analytics-data");
  if (!dataEl) return;

  if (typeof window.Chart === "undefined") {
    // CDN blocked or SRI mismatch: the stats and "Show data" tables still work.
    document.querySelectorAll("[data-chart-error]").forEach(function (el) { el.hidden = false; });
    return;
  }

  var data = JSON.parse(dataEl.textContent);
  var Chart = window.Chart;

  // --- Theme --------------------------------------------------------------
  var css = getComputedStyle(document.documentElement);
  function token(name, fallback) { return css.getPropertyValue(name).trim() || fallback; }

  var INK_SOFT = token("--color-ink-soft", "#4A4A4A");
  var EMBER = token("--color-ember", "#D9541E");
  var GRID = token("--color-cream-dark", "#EAE3D6");
  var NEUTRAL = "#BDB3A3"; // non-highlighted bars: warm grey that reads on the white cards
  var REST = "#D9D3C7";    // the donut's "Everything else" slice and its legend dots

  // 8 muted category colours, assigned in by_category order (largest first).
  // Ember is never a category colour: it only highlights (biggest day, selected month, this month's line).
  var PALETTE = [
    "#2F4858", // deep slate
    "#5B8E7D", // sage
    "#C9A227", // ochre
    "#7B6D8D", // muted plum
    "#B5838D", // dusty rose  (kept away from plum's closest neighbour, dusty blue)
    "#4F7CAC", // dusty blue
    "#8A9A5B", // olive
    "#6B4E3D"  // cocoa
  ];

  // --- Money (same output as the Jinja `money` filter) ---------------------
  function money(value) {
    var n = Math.round(Number(value) * 100) / 100;
    var paise = Math.round(n * 100) % 100 !== 0;
    return "Rs " + n.toLocaleString("en-US", {
      minimumFractionDigits: paise ? 2 : 0,
      maximumFractionDigits: paise ? 2 : 0
    });
  }

  // Axis ticks: Rs 500, Rs 1k, Rs 1.5k, Rs 12k, Rs 1.2M
  function moneyShort(value) {
    var n = Number(value);
    function oneDecimal(x) { return (Math.round(x * 10) / 10).toString(); }
    if (n >= 1e6) return "Rs " + oneDecimal(n / 1e6) + "M";
    if (n >= 1000) return "Rs " + oneDecimal(n / 1000) + "k";
    return "Rs " + n;
  }

  function pctText(pct, value) { return pct === 0 && value > 0 ? "<1%" : pct + "%"; }

  // --- Click / tap ---------------------------------------------------------
  // Mouse: a click follows the bar's link. Touch: the first tap only shows the tooltip
  // (Chart.js shows it on touchstart); tapping the same bar again follows the link.
  var noHover = window.matchMedia("(hover: none)");

  function followOnClick(urlAt) {
    var armed = null;
    return function (event, elements) {
      if (!elements.length) { armed = null; return; }
      var index = elements[0].index;
      var url = urlAt(index);
      if (!url) return;
      var touch = (event.native && event.native.pointerType === "touch") || noHover.matches;
      if (touch && armed !== index) { armed = index; return; }
      window.location.href = url;
    };
  }

  function pointerCursor(event, elements, chart) {
    chart.canvas.style.cursor = elements.length ? "pointer" : "default";
  }

  function yScale() {
    return {
      beginAtZero: true,
      border: { display: false },
      grid: { color: GRID },
      ticks: { maxTicksLimit: 5, callback: moneyShort }
    };
  }

  // --- Charts --------------------------------------------------------------
  function drawDonut() {
    var canvas = document.getElementById("chart-donut");
    if (!canvas || !data.categories.length) return;

    var limit = data.donut_slices;
    var top = data.categories.slice(0, limit);
    var rest = data.categories.length > limit ? data.categories.slice(limit) : [];
    var labels = [], values = [], colors = [], pcts = [];

    top.forEach(function (c, i) {
      labels.push(c.name);
      values.push(Number(c.total));
      colors.push(PALETTE[i % PALETTE.length]);
      pcts.push(c.pct);
    });
    if (rest.length) {
      // Plain adding of totals the database already summed.
      var sum = rest.reduce(function (s, c) { return s + Number(c.total); }, 0);
      labels.push("Everything else");
      values.push(sum);
      colors.push(REST);
      pcts.push(Math.round(sum / Number(data.total) * 100));
    }

    // Colour the HTML legend dots to match their slice (grouped categories get the grey).
    document.querySelectorAll("[data-legend-index]").forEach(function (dot) {
      var i = Number(dot.getAttribute("data-legend-index"));
      dot.style.backgroundColor = rest.length && i >= limit ? REST : PALETTE[i % PALETTE.length];
    });

    new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: labels,
        datasets: [{ data: values, backgroundColor: colors, borderColor: "#FFFFFF", borderWidth: 2, hoverOffset: 4 }]
      },
      options: {
        cutout: "68%",
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: function () { return ""; },
              label: function (item) {
                return labels[item.dataIndex] + " · " + money(values[item.dataIndex]) + " · " +
                  pctText(pcts[item.dataIndex], values[item.dataIndex]);
              }
            }
          }
        }
      }
    });
  }

  function drawDaily() {
    var canvas = document.getElementById("chart-daily");
    if (!canvas || !data.daily.length) return;

    var totals = data.daily.map(function (d) { return Number(d.total); });
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: data.daily.map(function (d) { return d.day; }),
        datasets: [{
          data: totals,
          backgroundColor: totals.map(function (_, i) { return i === data.biggest_day_index ? EMBER : NEUTRAL; }),
          borderRadius: 4,
          maxBarThickness: 28
        }]
      },
      options: {
        // The whole day column is the tap target, so thin bars are easy to hit on phones.
        interaction: { mode: "index", intersect: false },
        onClick: followOnClick(function (i) { return data.daily[i].url; }),
        onHover: pointerCursor,
        plugins: {
          legend: { display: false },
          tooltip: {
            displayColors: false,
            callbacks: {
              title: function (items) { return data.daily[items[0].dataIndex].label; },
              label: function (item) { return money(item.raw); }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              autoSkip: false,
              maxRotation: 0,
              // Narrow charts show only day 1 and every 5th day.
              callback: function (value, index) {
                var day = index + 1;
                return this.chart.width < 480 && day !== 1 && day % 5 !== 0 ? "" : day;
              }
            }
          },
          y: yScale()
        }
      }
    });
  }

  function drawCumulative() {
    var canvas = document.getElementById("chart-cumulative");
    if (!canvas || !data.daily.length) return;

    var length = Math.max(data.days_in_month, data.prev_daily.length);
    var labels = [], current = [], previous = [];
    for (var i = 0; i < length; i++) {
      labels.push(i + 1);
      current.push(i < data.daily.length ? Number(data.daily[i].running) : null);
      previous.push(i < data.prev_daily.length ? Number(data.prev_daily[i].running) : null);
    }

    var datasets = [{
      label: data.month_short,
      data: current,
      borderColor: EMBER,
      backgroundColor: EMBER,
      borderWidth: 2.5,
      pointRadius: 0,
      pointHoverRadius: 4,
      cubicInterpolationMode: "monotone",
      spanGaps: false
    }];
    if (data.has_prev) {
      datasets.push({
        label: data.prev_short,
        data: previous,
        borderColor: INK_SOFT,
        backgroundColor: INK_SOFT,
        borderDash: [6, 4],
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        cubicInterpolationMode: "monotone",
        spanGaps: false
      });
    }

    new Chart(canvas, {
      type: "line",
      data: { labels: labels, datasets: datasets },
      options: {
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false }, // HTML legend above the chart
          tooltip: {
            filter: function (item) { return item.raw !== null; },
            callbacks: {
              title: function (items) { return "Day " + items[0].label; },
              label: function (item) { return item.dataset.label + " " + money(item.raw); }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkipPadding: 8 } },
          y: yScale()
        }
      }
    });
  }

  function drawSixMonths() {
    var canvas = document.getElementById("chart-six");
    if (!canvas || !data.six_months.length) return;

    var months = data.six_months;
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: months.map(function (m) { return m.label; }),
        datasets: [{
          data: months.map(function (m) { return Number(m.total); }),
          backgroundColor: months.map(function (m) { return m.selected ? EMBER : NEUTRAL; }),
          borderRadius: 6,
          maxBarThickness: 48
        }]
      },
      options: {
        interaction: { mode: "index", intersect: false },
        onClick: followOnClick(function (i) { return months[i].selected ? null : months[i].url; }),
        onHover: pointerCursor,
        plugins: {
          legend: { display: false },
          tooltip: {
            displayColors: false,
            callbacks: {
              title: function (items) { return months[items[0].dataIndex].title; },
              label: function (item) { return money(item.raw); }
            }
          }
        },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0 } },
          y: yScale()
        }
      }
    });
  }

  function drawAll() {
    Chart.defaults.font.family = "Inter, ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif";
    Chart.defaults.color = INK_SOFT;
    Chart.defaults.responsive = true;
    Chart.defaults.maintainAspectRatio = false;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) Chart.defaults.animation = false;

    drawDonut();
    drawDaily();
    drawCumulative();
    drawSixMonths();
  }

  // Wait for Inter so the canvas text uses it.
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(drawAll, drawAll);
  } else {
    drawAll();
  }
})();
