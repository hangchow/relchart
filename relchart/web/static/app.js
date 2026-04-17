function requestedStocksQuery() {
  return new URLSearchParams(window.location.search).get("stocks") || "";
}

function clearChart() {
  const chart = document.getElementById("chart");
  if (chart && window.Plotly) {
    window.Plotly.purge(chart);
  }
  if (chart) {
    chart.innerHTML = "";
    chart.classList.remove("chart-empty");
  }
}

function renderEmptyState(title, detail) {
  const chart = document.getElementById("chart");
  clearChart();
  if (!chart) {
    return;
  }

  chart.classList.add("chart-empty");
  const detailHtml = detail ? `<p class="empty-state-detail">${detail}</p>` : "";
  chart.innerHTML = `
    <div class="empty-state">
      <h2 class="empty-state-title">${title}</h2>
      ${detailHtml}
    </div>
  `;
}

function renderLegend(series) {
  const legend = document.getElementById("legend");
  legend.innerHTML = "";
  series.forEach((item) => {
    const primary = item.display_name || item.symbol;
    const secondary = item.display_name && item.display_name !== item.symbol
      ? `<span class="legend-code">${item.symbol}</span>`
      : "";
    const row = document.createElement("div");
    row.className = "legend-item";
    row.innerHTML = `
      <span class="legend-swatch" style="background:${item.color}"></span>
      <span class="legend-text">
        <span class="legend-label">${primary}</span>
        ${secondary}
      </span>
    `;
    legend.appendChild(row);
  });
}

function renderWarnings(warnings) {
  const warningsEl = document.getElementById("warnings");
  if (!warnings || warnings.length === 0) {
    warningsEl.hidden = true;
    warningsEl.innerHTML = "";
    return;
  }

  warningsEl.hidden = false;
  warningsEl.innerHTML = warnings
    .map((text) => `<div class="warning-item">${text}</div>`)
    .join("");
}

function buildTraces(series) {
  const traces = [];
  series.forEach((item) => {
    if (item.series_type === "line") {
      const lineX = item.points.map((point) => point.time);
      const lineY = item.points.map((point) => point.value);
      const lineCustomData = item.points.map((point) => point.raw_value);
      let markerOpacity = 0;
      let markerSymbol = "circle";

      if (item.provisional_point) {
        lineX.push(null, item.provisional_point.time);
        lineY.push(null, item.provisional_point.value);
        lineCustomData.push(null, item.provisional_point.raw_value);
        markerOpacity = item.points.map(() => 0).concat([0, 1]);
        markerSymbol = item.points.map(() => "circle").concat(["circle", "diamond-open"]);
      }

      traces.push({
        type: "scatter",
        mode: "lines+markers",
        name: item.display_name || item.symbol,
        x: lineX,
        y: lineY,
        customdata: lineCustomData,
        line: {
          color: item.color,
          width: 2.5,
        },
        marker: {
          size: 10,
          opacity: markerOpacity,
          color: item.color,
          symbol: markerSymbol,
        },
        hoverlabel: {
          bgcolor: "rgba(255,255,255,0.96)",
          bordercolor: item.color,
          font: { color: "#0f172a", size: 12 },
        },
        hovertemplate: [
          `<b>${item.display_name || item.symbol}</b>`,
          item.display_name && item.display_name !== item.symbol ? item.symbol : null,
          "Date %{x|%Y-%m-%d}",
          "Ratio %{customdata:.4f}",
          "Change %{y:.2f}%",
          "<extra></extra>",
        ].filter(Boolean).join("<br>"),
      });

      if (item.provisional_point) {
        const previousPoint = item.points.length > 0 ? item.points[item.points.length - 1] : null;
        if (previousPoint) {
          traces.push({
            type: "scatter",
            mode: "lines",
            x: [previousPoint.time, item.provisional_point.time],
            y: [previousPoint.value, item.provisional_point.value],
            line: {
              color: item.color,
              width: 3,
              dash: "dot",
            },
            hoverinfo: "skip",
            showlegend: false,
          });
        }
      }
      return;
    }

    traces.push({
      type: "candlestick",
      name: item.display_name || item.symbol,
      x: item.bars.map((bar) => bar.time),
      open: item.bars.map((bar) => bar.open),
      high: item.bars.map((bar) => bar.high),
      low: item.bars.map((bar) => bar.low),
      close: item.bars.map((bar) => bar.close),
      increasing: {
        line: { color: item.color, width: 1.25 },
        fillcolor: item.color,
      },
      decreasing: {
        line: { color: item.color, width: 1.25 },
        fillcolor: item.color,
      },
      whiskerwidth: 0.3,
      opacity: 0.62,
      hoverlabel: {
        bgcolor: "rgba(255,255,255,0.96)",
        bordercolor: item.color,
        font: { color: "#0f172a", size: 12 },
      },
      hovertemplate: [
        `<b>${item.display_name || item.symbol}</b>`,
        item.display_name && item.display_name !== item.symbol ? item.symbol : null,
        "Date %{x|%Y-%m-%d}",
        "Open %{open:.2f}%",
        "High %{high:.2f}%",
        "Low %{low:.2f}%",
        "Close %{close:.2f}%",
        "<extra></extra>",
      ].filter(Boolean).join("<br>"),
    });

    if (item.provisional_bar) {
      traces.push({
        type: "candlestick",
        name: `${item.display_name || item.symbol} provisional`,
        x: [item.provisional_bar.time],
        open: [item.provisional_bar.open],
        high: [item.provisional_bar.high],
        low: [item.provisional_bar.low],
        close: [item.provisional_bar.close],
        increasing: {
          line: { color: item.color, width: 2 },
          fillcolor: item.color,
        },
        decreasing: {
          line: { color: item.color, width: 2 },
          fillcolor: item.color,
        },
        whiskerwidth: 0.4,
        opacity: 0.3,
        hoverlabel: {
          bgcolor: "rgba(255,255,255,0.96)",
          bordercolor: item.color,
          font: { color: "#0f172a", size: 12 },
        },
        hovertemplate: [
          `<b>${item.display_name || item.symbol}</b>`,
          item.display_name && item.display_name !== item.symbol ? item.symbol : null,
          "Date %{x|%Y-%m-%d}",
          "Open %{open:.2f}%",
          "High %{high:.2f}%",
          "Low %{low:.2f}%",
          "Close %{close:.2f}%",
          "Status provisional",
          "<extra></extra>",
        ].filter(Boolean).join("<br>"),
      });
    }
  });

  return traces;
}

function hasProvisionalData(snapshot) {
  return (snapshot.series || []).some((item) => item.provisional_bar || item.provisional_point);
}

function renderChart(snapshot) {
  const chart = document.getElementById("chart");
  chart.classList.remove("chart-empty");
  const traces = buildTraces(snapshot.series);
  const layout = {
    template: "none",
    paper_bgcolor: "#fffdf8",
    plot_bgcolor: "#fffdf8",
    margin: { l: 72, r: 32, t: 24, b: 48 },
    showlegend: false,
    hovermode: "x unified",
    hoverdistance: 40,
    dragmode: false,
    xaxis: {
      type: "date",
      fixedrange: true,
      rangeslider: { visible: false },
      showgrid: true,
      gridcolor: "#e7e0d4",
      tickfont: { size: 12, color: "#4b5563" },
    },
    yaxis: {
      title: { text: "% from base close", font: { size: 13, color: "#4b5563" } },
      fixedrange: true,
      showgrid: true,
      zeroline: true,
      zerolinecolor: "#c89b3c",
      zerolinewidth: 1,
      gridcolor: "#ece6db",
      tickfont: { size: 12, color: "#4b5563" },
      ticksuffix: "%",
    },
  };
  const config = {
    responsive: true,
    displaylogo: false,
    displayModeBar: false,
    scrollZoom: false,
    doubleClick: false,
  };

  Plotly.react(chart, traces, layout, config);
}

function displayTitle(snapshot) {
  const labels = (snapshot.series || []).map((item) => item.display_name || item.symbol);
  if (labels.length > 0) {
    return labels.join(" · ");
  }
  return (snapshot.requested_symbols || []).join(" · ") || snapshot.title || "Relative Daily K Overlay";
}

async function load() {
  const title = document.getElementById("title");
  const meta = document.getElementById("meta");
  const stocksQuery = requestedStocksQuery().trim();

  if (!stocksQuery) {
    title.textContent = "relchart";
    meta.textContent = "Open /kline?stocks=US.AAPL,US.TSLA";
    renderLegend([]);
    renderWarnings(["No stocks selected in the stocks query parameter."]);
    renderEmptyState(
      "No chart data available",
      "Add at least one stock code in the stocks query parameter.",
    );
    return;
  }

  try {
    const response = await fetch(`/api/chart-data?stocks=${encodeURIComponent(stocksQuery)}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `request failed: ${response.status}`);
    }
    const snapshot = await response.json();
    title.textContent = displayTitle(snapshot);
    const provisionalSuffix = hasProvisionalData(snapshot)
      ? " · includes provisional current-trading-day data"
      : "";
    meta.textContent = `Window ${snapshot.window.start} to ${snapshot.window.end} · generated ${new Date(snapshot.generated_at).toLocaleString()}${provisionalSuffix}`;
    renderLegend(snapshot.series || []);
    const warnings = snapshot.warnings || [];
    if (!snapshot.series || snapshot.series.length === 0) {
      renderWarnings(
        warnings.length > 0
          ? warnings
          : ["No chart data available for the requested window."],
      );
      renderEmptyState(
        "No chart data available",
        warnings.length > 0
          ? "See the warnings above for the current data availability state."
          : "No cached bars were available for the requested window.",
      );
      return;
    }

    renderWarnings(warnings);
    renderChart(snapshot);
  } catch (error) {
    title.textContent = "relchart";
    meta.textContent = String(error);
    renderLegend([]);
    renderWarnings([String(error)]);
    renderEmptyState("Request failed", String(error));
  }
}

window.addEventListener("load", load);
window.addEventListener("resize", () => {
  const chart = document.getElementById("chart");
  if (chart && window.Plotly && window.Plotly.Plots) {
    window.Plotly.Plots.resize(chart);
  }
});
