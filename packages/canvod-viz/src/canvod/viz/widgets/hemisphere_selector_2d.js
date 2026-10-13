// 2D Hemisphere Selector — Canvas-based polar projection anywidget
// Renders cells as dots on a polar stereographic projection (North-up).

// Viridis LUT (16 stops, interpolated)
const VIRIDIS = [
  [68, 1, 84],
  [72, 26, 108],
  [71, 47, 125],
  [65, 68, 135],
  [57, 86, 140],
  [49, 104, 142],
  [42, 120, 142],
  [35, 137, 140],
  [31, 154, 138],
  [34, 170, 131],
  [53, 186, 116],
  [86, 198, 103],
  [122, 209, 81],
  [165, 218, 54],
  [210, 226, 27],
  [253, 231, 37],
];

function viridisColor(t) {
  // t in [0, 1]
  t = Math.max(0, Math.min(1, t));
  const idx = t * (VIRIDIS.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.min(lo + 1, VIRIDIS.length - 1);
  const f = idx - lo;
  const r = Math.round(VIRIDIS[lo][0] * (1 - f) + VIRIDIS[hi][0] * f);
  const g = Math.round(VIRIDIS[lo][1] * (1 - f) + VIRIDIS[hi][1] * f);
  const b = Math.round(VIRIDIS[lo][2] * (1 - f) + VIRIDIS[hi][2] * f);
  return `rgb(${r},${g},${b})`;
}

function render({ model, el }) {
  const size = model.get("canvas_size");
  const container = document.createElement("div");
  container.className = "hemisphere-container";
  container.style.width = size + "px";
  container.style.height = size + "px";

  const canvas = document.createElement("canvas");
  canvas.width = size * 2; // retina
  canvas.height = size * 2;
  canvas.style.width = size + "px";
  canvas.style.height = size + "px";
  container.appendChild(canvas);

  const tooltip = document.createElement("div");
  tooltip.className = "hemisphere-tooltip";
  container.appendChild(tooltip);

  el.appendChild(container);

  const ctx = canvas.getContext("2d");
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  const radius = canvas.width * 0.42;

  // Convert (theta, phi) to canvas (px, py)
  // theta: zenith (0=center), phi: azimuth (0=North=up, CW)
  function toCanvas(theta, phi) {
    const r = (theta / (Math.PI / 2)) * radius;
    // phi=0 is North (up), canvas y is inverted
    const px = cx + r * Math.sin(phi);
    const py = cy - r * Math.cos(phi);
    return [px, py];
  }

  function draw() {
    const thetas = model.get("cell_theta");
    const phis = model.get("cell_phi");
    const values = model.get("cell_values");
    const selected = new Set(model.get("selected_cell_ids"));

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Draw grid rings
    ctx.strokeStyle = "#ccc";
    ctx.lineWidth = 1;
    for (let deg = 0; deg <= 90; deg += 30) {
      const r = (deg / 90) * radius;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, 2 * Math.PI);
      ctx.stroke();
    }
    // Meridians
    for (let a = 0; a < 360; a += 45) {
      const rad = (a * Math.PI) / 180;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + radius * Math.sin(rad), cy - radius * Math.cos(rad));
      ctx.stroke();
    }

    // Labels
    ctx.fillStyle = "#666";
    ctx.font = `${canvas.width * 0.025}px sans-serif`;
    ctx.textAlign = "center";
    ["N", "E", "S", "W"].forEach((label, i) => {
      const a = (i * Math.PI) / 2;
      const lr = radius + canvas.width * 0.04;
      ctx.fillText(label, cx + lr * Math.sin(a), cy - lr * Math.cos(a) + 5);
    });

    // Normalize values
    let vmin = Infinity,
      vmax = -Infinity;
    for (const v of values) {
      if (isFinite(v)) {
        if (v < vmin) vmin = v;
        if (v > vmax) vmax = v;
      }
    }
    const vrange = vmax - vmin || 1;

    // Draw cells
    const dotRadius = Math.max(3, radius / Math.sqrt(thetas.length) * 0.8);
    for (let i = 0; i < thetas.length; i++) {
      const [px, py] = toCanvas(thetas[i], phis[i]);
      const t = (values[i] - vmin) / vrange;

      ctx.beginPath();
      ctx.arc(px, py, dotRadius, 0, 2 * Math.PI);
      ctx.fillStyle = viridisColor(t);
      ctx.fill();

      if (selected.has(i)) {
        ctx.strokeStyle = "red";
        ctx.lineWidth = 3;
        ctx.stroke();
      }
    }
  }

  draw();

  // Hit detection
  function findCell(canvasX, canvasY) {
    const thetas = model.get("cell_theta");
    const phis = model.get("cell_phi");
    const dotR = Math.max(3, radius / Math.sqrt(thetas.length) * 0.8);
    let best = -1,
      bestDist = Infinity;
    for (let i = 0; i < thetas.length; i++) {
      const [px, py] = toCanvas(thetas[i], phis[i]);
      const d = Math.hypot(canvasX - px, canvasY - py);
      if (d < dotR + 4 && d < bestDist) {
        best = i;
        bestDist = d;
      }
    }
    return best;
  }

  canvas.addEventListener("click", (e) => {
    const rect = canvas.getBoundingClientRect();
    const sx = (canvas.width / rect.width);
    const cx = (e.clientX - rect.left) * sx;
    const cy = (e.clientY - rect.top) * sx;
    const idx = findCell(cx, cy);
    if (idx < 0) return;
    const selected = new Set(model.get("selected_cell_ids"));
    if (selected.has(idx)) selected.delete(idx);
    else selected.add(idx);
    model.set("selected_cell_ids", [...selected]);
    model.save_changes();
    draw();
  });

  canvas.addEventListener("mousemove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const sx = (canvas.width / rect.width);
    const cx = (e.clientX - rect.left) * sx;
    const cy = (e.clientY - rect.top) * sx;
    const idx = findCell(cx, cy);
    model.set("hovered_cell_id", idx);
    model.save_changes();

    const labels = model.get("cell_labels");
    if (idx >= 0 && labels[idx]) {
      tooltip.textContent = labels[idx];
      tooltip.style.display = "block";
      tooltip.style.left = e.clientX - rect.left + 12 + "px";
      tooltip.style.top = e.clientY - rect.top - 20 + "px";
    } else {
      tooltip.style.display = "none";
    }
  });

  canvas.addEventListener("mouseleave", () => {
    tooltip.style.display = "none";
    model.set("hovered_cell_id", -1);
    model.save_changes();
  });

  model.on("change:cell_values", draw);
  model.on("change:selected_cell_ids", draw);
}

export default { render };
