function requestedStocksQuery() {
  return new URLSearchParams(window.location.search).get("stocks") || "";
}

function clearChart() {
  const chart = document.getElementById("chart");
  if (chart && window.Plotly) {
    window.Plotly.purge(chart);
  }
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
  return series.map((item) => {
    if (item.series_type === "line") {
      return {
        type: "scatter",
        mode: "lines+markers",
        name: item.display_name || item.symbol,
        x: item.points.map((point) => point.time),
        y: item.points.map((point) => point.value),
        customdata: item.points.map((point) => point.raw_value),
        line: {
          color: item.color,
          width: 2.5,
        },
        marker: {
          size: 10,
          opacity: 0,
          color: item.color,
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
      };
    }

    return {
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
    };
  });
}

function renderChart(snapshot) {
  const chart = document.getElementById("chart");
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
    clearChart();
    return;
  }

  try {
    const response = await fetch(`/api/chart-data?stocks=${encodeURIComponent(stocksQuery)}`);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `request failed: ${response.status}`);
    }
    const snapshot = await response.json();
    if (!snapshot.series || snapshot.series.length === 0) {
      throw new Error("no chart series available");
    }

    title.textContent = displayTitle(snapshot);
    meta.textContent = `Window ${snapshot.window.start} to ${snapshot.window.end} · generated ${new Date(snapshot.generated_at).toLocaleString()}`;
    renderLegend(snapshot.series);
    renderWarnings(snapshot.warnings || []);
    renderChart(snapshot);
  } catch (error) {
    title.textContent = "relchart";
    meta.textContent = String(error);
    renderLegend([]);
    renderWarnings([String(error)]);
    clearChart();
  }
}

window.addEventListener("load", load);
window.addEventListener("resize", () => {
  const chart = document.getElementById("chart");
  if (chart && window.Plotly && window.Plotly.Plots) {
    window.Plotly.Plots.resize(chart);
  }
});
