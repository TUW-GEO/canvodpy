// 3D Hemisphere Selector — Plotly Scatter3d anywidget
// Renders cell centers on a unit hemisphere with click-to-select.

const PLOTLY_CDN = "https://cdn.plot.ly/plotly-2.35.2.min.js";

let plotlyReady;

function loadPlotly() {
  if (plotlyReady) return plotlyReady;
  if (window.Plotly) {
    plotlyReady = Promise.resolve(window.Plotly);
    return plotlyReady;
  }
  plotlyReady = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = PLOTLY_CDN;
    script.onload = () => resolve(window.Plotly);
    script.onerror = reject;
    document.head.appendChild(script);
  });
  return plotlyReady;
}

function render({ model, el }) {
  const container = document.createElement("div");
  container.className = "hemisphere-container";
  container.style.width = "100%";
  container.style.height = "550px";
  el.appendChild(container);

  loadPlotly().then((Plotly) => {
    function buildTraces() {
      const x = model.get("cell_centers_x");
      const y = model.get("cell_centers_y");
      const z = model.get("cell_centers_z");
      const values = model.get("cell_values");
      const labels = model.get("cell_labels");
      const selected = new Set(model.get("selected_cell_ids"));
      const colorscale = model.get("colorscale");
      const markerSize = model.get("marker_size");

      // Color array: selected cells get highlighted
      const colors = values.map((v, i) => (selected.has(i) ? null : v));
      const outlineColors = values.map((_, i) =>
        selected.has(i) ? "red" : "rgba(0,0,0,0)"
      );
      const sizes = values.map((_, i) =>
        selected.has(i) ? markerSize + 4 : markerSize
      );
      const outlineWidths = values.map((_, i) => (selected.has(i) ? 2 : 0));

      return [
        {
          type: "scatter3d",
          mode: "markers",
          x,
          y,
          z,
          text: labels,
          hoverinfo: "text",
          marker: {
            size: sizes,
            color: values,
            colorscale,
            showscale: true,
            colorbar: { title: "Value", len: 0.6 },
            line: { color: outlineColors, width: outlineWidths },
          },
        },
      ];
    }

    const layout = {
      scene: {
        xaxis: { title: "East", range: [-1.1, 1.1] },
        yaxis: { title: "North", range: [-1.1, 1.1] },
        zaxis: { title: "Up", range: [0, 1.1] },
        aspectmode: "cube",
        camera: { eye: { x: 1.5, y: 1.5, z: 1.0 } },
      },
      margin: { l: 0, r: 0, t: 30, b: 0 },
      paper_bgcolor: "rgba(0,0,0,0)",
    };

    Plotly.newPlot(container, buildTraces(), layout, {
      responsive: true,
    }).then(() => {
      // Click handler — toggle cell selection
      container.on("plotly_click", (data) => {
        if (!data.points || !data.points.length) return;
        const idx = data.points[0].pointNumber;
        const selected = new Set(model.get("selected_cell_ids"));
        if (selected.has(idx)) {
          selected.delete(idx);
        } else {
          selected.add(idx);
        }
        model.set("selected_cell_ids", [...selected]);
        model.save_changes();
        Plotly.react(container, buildTraces(), layout);
      });

      // Hover handler
      container.on("plotly_hover", (data) => {
        if (data.points && data.points.length) {
          model.set("hovered_cell_id", data.points[0].pointNumber);
          model.save_changes();
        }
      });
      container.on("plotly_unhover", () => {
        model.set("hovered_cell_id", -1);
        model.save_changes();
      });
    });

    // Re-render when data changes from Python side
    model.on("change:cell_values", () => {
      Plotly.react(container, buildTraces(), layout);
    });
    model.on("change:selected_cell_ids", () => {
      Plotly.react(container, buildTraces(), layout);
    });
  });
}

export default { render };
