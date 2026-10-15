const state = { step: 0, sessionId: null, upload: null, mapping: null, calibration: null, treatmentUpload: null, treatmentMapping: null, treatment: null, simulation: null, scenarios: [{ name: "Protocol A", days: "7,14,21", doses: "1,1,1" }] };
const stages = ["Data", "Calibration", "Results", "Treatment", "Experiments", "Report"];
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[char]));
const api = async (path, options = {}) => { const response = await fetch(path, options); const raw = await response.text(); let body; try { body = raw ? JSON.parse(raw) : {}; } catch { throw new Error(`The server returned HTTP error ${response.status}: ${raw.slice(0, 180)}`); } if (!response.ok) throw new Error(body.detail || `Server error (${response.status})`); return body; };
const select = (label, name, value, options) => `<div class="field"><label>${label}</label><select name="${name}">${options.map((option) => `<option value="${esc(option)}" ${option === value ? "selected" : ""}>${esc(option)}</option>`).join("")}</select></div>`;
const palette = ["#1c3a13", "#c8703f", "#3d6078", "#9a6a34", "#7b3f5c", "#456b8c", "#8a8a3e", "#5c3a8a", "#b34d4d", "#2f7f75", "#c28b2c", "#6b4c9a", "#3f6f9f", "#a65e86", "#4d843d", "#bd6f2d"];
const colorFor = (index) => palette[index % palette.length];
const treatmentEquations = {
  ED: "C(t) = Σ a·d·exp(−b·Δ)",
  CD: "C(t) = Σ a·D_cumulative·exp(−b·Δ)",
  AccelED: "C(t) = Σ a·d·exp(−b·Δ²)",
  MM: "C(t) = Σ a·d / (1 + b·d)",
  LS: "C(t,V) = Σ a·d / (1 + b·V)",
  dePR: "C(t,V) = Σ δ·d^λ / (s·V^λ + d^λ)",
  T_hill: "C(s) = dmax·sⁿ / (τⁿ + sⁿ)",
  T_expon: "C(s) = dmax·(1 − exp(−λ·s))",
  T_pulso: "C(s) = k·s·exp(−s/τ)",
  T_rampa: "C(s) = a·s",
  T_hill_sat: "Tumour death = dmax·[sⁿ/(τⁿ+sⁿ)]·V/(h+V)",
};
const treatmentModels = ["ED", "CD", "AccelED", "MM", "LS", "dePR", "T_hill", "T_expon", "T_pulso", "T_rampa", "T_hill_sat"];

// Reusable zoomable line/scatter chart: drag-select to zoom in on both axes,
// mouse wheel to zoom around the cursor, double-click or the reset button to
// go back to the full view. `series` is [{label, color, points:[[x,y],...], dashed, style:"line"|"points"}].
function mountChart(container, series, opts = {}) {
  if (!container) return;
  const width = opts.width || 640, height = opts.height || 260;
  const margin = { top: 10, right: 14, bottom: 30, left: 50 };
  const plotW = width - margin.left - margin.right, plotH = height - margin.top - margin.bottom;
  const hidden = new Set();
  const fmt = (value) => (Math.abs(value) >= 100 ? Math.round(value).toString() : (Math.round(value * 100) / 100).toString());
  const fullDomain = () => {
    const points = series.flatMap((item) => item.points);
    const xs = points.map((point) => point[0]), ys = points.map((point) => point[1]);
    let xMin = Math.min(...xs, 0), xMax = Math.max(...xs, 1), yMin = opts.yMinZero ? 0 : Math.min(...ys), yMax = Math.max(...ys, opts.yMinZero ? 1 : 1);
    if (opts.symmetricY) { const bound = Math.max(Math.abs(yMin), Math.abs(yMax), 1e-6); yMin = -bound; yMax = bound; }
    const xPad = (xMax - xMin) * 0.04 || 1, yPad = (yMax - yMin) * 0.1 || 1;
    return { xMin: xMin - xPad, xMax: xMax + xPad, yMin: opts.yMinZero ? 0 : yMin - yPad, yMax: yMax + yPad };
  };
  let domain = fullDomain();
  const isZoomed = () => { const full = fullDomain(); return Math.abs(domain.xMin - full.xMin) > 1e-6 || Math.abs(domain.xMax - full.xMax) > 1e-6 || Math.abs(domain.yMin - full.yMin) > 1e-6 || Math.abs(domain.yMax - full.yMax) > 1e-6; };
  const sx = (x) => margin.left + ((x - domain.xMin) / (domain.xMax - domain.xMin || 1)) * plotW;
  const sy = (y) => margin.top + plotH - ((y - domain.yMin) / (domain.yMax - domain.yMin || 1)) * plotH;
  const ux = (px) => domain.xMin + ((px - margin.left) / plotW) * (domain.xMax - domain.xMin);
  const uy = (py) => domain.yMin + ((margin.top + plotH - py) / plotH) * (domain.yMax - domain.yMin);
  const niceTicks = (min, max, count) => { const span = max - min || 1; const rawStep = span / count; const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep))); const residual = rawStep / magnitude; const mult = residual >= 7.5 ? 10 : residual >= 3 ? 5 : residual >= 1.5 ? 2 : 1; const step = magnitude * mult || 1; const start = Math.ceil(min / step) * step; const ticks = []; for (let value = start; value <= max + step / 1e6; value += step) ticks.push(Math.round(value * 1e6) / 1e6); return ticks; };

  function draw() {
    const xTicks = niceTicks(domain.xMin, domain.xMax, 6);
    const yTicks = niceTicks(domain.yMin, domain.yMax, 5);
    const grid = [
      ...xTicks.map((t) => `<line x1="${sx(t).toFixed(1)}" y1="${margin.top}" x2="${sx(t).toFixed(1)}" y2="${margin.top + plotH}" class="chart-grid"/>`),
      ...yTicks.map((t) => `<line x1="${margin.left}" y1="${sy(t).toFixed(1)}" x2="${margin.left + plotW}" y2="${sy(t).toFixed(1)}" class="chart-grid"/>`),
    ].join("");
    const labels = [
      ...xTicks.map((t) => `<text x="${sx(t).toFixed(1)}" y="${margin.top + plotH + 18}" class="chart-tick" text-anchor="middle">${fmt(t)}</text>`),
      ...yTicks.map((t) => `<text x="${margin.left - 8}" y="${(sy(t) + 3).toFixed(1)}" class="chart-tick" text-anchor="end">${fmt(t)}</text>`),
    ].join("");
    const zero = opts.zeroLine != null && domain.yMin < opts.zeroLine && domain.yMax > opts.zeroLine ? `<line x1="${margin.left}" y1="${sy(opts.zeroLine).toFixed(1)}" x2="${margin.left + plotW}" y2="${sy(opts.zeroLine).toFixed(1)}" class="chart-zero"/>` : "";
    const drawn = series.map((item) => {
      if (hidden.has(item.label)) return "";
      const points = item.points.filter((point) => point[0] >= domain.xMin && point[0] <= domain.xMax);
      if (item.style === "points") return points.map((point) => `<circle cx="${sx(point[0]).toFixed(1)}" cy="${sy(point[1]).toFixed(1)}" r="3.2" fill="${item.color}" opacity="0.85"/>`).join("");
      const path = points.map((point, index) => `${index ? "L" : "M"}${sx(point[0]).toFixed(1)},${sy(point[1]).toFixed(1)}`).join(" ");
      return `<path d="${path}" fill="none" stroke="${item.color}" stroke-width="${item.width || 2}" ${item.dashed ? 'stroke-dasharray="6 5"' : ""} opacity="${item.opacity ?? 1}"/>`;
    }).join("");
    container.innerHTML = `
      <div class="chart-toolbar">${opts.title ? `<span class="chart-title">${esc(opts.title)}</span>` : "<span></span>"}<button type="button" class="chart-reset" ${isZoomed() ? "" : "hidden"}>⤾ Reset zoom</button></div>
      <svg viewBox="0 0 ${width} ${height}" class="zoom-chart" role="img" aria-label="${esc(opts.ariaLabel || opts.title || "chart")}">
        <rect x="${margin.left}" y="${margin.top}" width="${plotW}" height="${plotH}" class="chart-bg"/>
        ${grid}${labels}${zero}${drawn}
        <rect class="chart-selection" x="0" y="0" width="0" height="0" hidden/>
        <rect x="${margin.left}" y="${margin.top}" width="${plotW}" height="${plotH}" class="chart-capture"/>
      </svg>
      ${opts.legend !== false ? `<div class="chart-legend">${series.map((item) => `<button type="button" class="legend-item ${hidden.has(item.label) ? "off" : ""}" data-label="${esc(item.label)}"><i class="legend-swatch" style="background:${item.color}${item.dashed ? `;background-image:linear-gradient(90deg,${item.color} 55%, transparent 55%);background-size:6px 3px` : ""}"></i>${esc(item.label)}</button>`).join("")}</div>` : ""}
      <div class="chart-hint">Drag to zoom · scroll to zoom in/out · double-click to reset</div>
      <div class="chart-tooltip" hidden></div>`;
    wire();
  }

  function wire() {
    const svg = container.querySelector(".zoom-chart");
    const capture = container.querySelector(".chart-capture");
    const selectionRect = container.querySelector(".chart-selection");
    const resetButton = container.querySelector(".chart-reset");
    const tooltip = container.querySelector(".chart-tooltip");
    const toLocal = (event) => { const rect = svg.getBoundingClientRect(); return { x: (event.clientX - rect.left) * (width / rect.width), y: (event.clientY - rect.top) * (height / rect.height) }; };
    capture.addEventListener("mousedown", (event) => {
      const start = toLocal(event);
      selectionRect.hidden = false;
      tooltip.hidden = true;
      const onMove = (moveEvent) => { const point = toLocal(moveEvent); selectionRect.setAttribute("x", Math.min(start.x, point.x)); selectionRect.setAttribute("y", Math.min(start.y, point.y)); selectionRect.setAttribute("width", Math.abs(point.x - start.x)); selectionRect.setAttribute("height", Math.abs(point.y - start.y)); };
      const onUp = (upEvent) => {
        const point = toLocal(upEvent);
        const w = Math.abs(point.x - start.x), h = Math.abs(point.y - start.y);
        if (w > 12 && h > 12) {
          const x0 = Math.min(start.x, point.x), x1 = Math.max(start.x, point.x), y0 = Math.min(start.y, point.y), y1 = Math.max(start.y, point.y);
          domain = { xMin: ux(x0), xMax: ux(x1), yMin: uy(y1), yMax: uy(y0) };
          draw();
        } else { selectionRect.hidden = true; selectionRect.setAttribute("width", 0); selectionRect.setAttribute("height", 0); }
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
      };
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    });
    capture.addEventListener("mousemove", (event) => {
      const point = toLocal(event);
      const xValue = ux(point.x);
      let closest = null, closestDistance = Infinity;
      series.forEach((item) => { if (hidden.has(item.label)) return; item.points.forEach((candidate) => { const distance = Math.abs(candidate[0] - xValue); if (distance < closestDistance) { closestDistance = distance; closest = { item, candidate }; } }); });
      if (closest) { tooltip.hidden = false; tooltip.style.left = `${(sx(closest.candidate[0]) / width) * 100}%`; tooltip.style.top = `${(sy(closest.candidate[1]) / height) * 100}%`; tooltip.innerHTML = `<b>${esc(closest.item.label)}</b><br>${esc(opts.xLabel || "x")}: ${fmt(closest.candidate[0])}<br>${esc(opts.yLabel || "y")}: ${fmt(closest.candidate[1])}`; }
    });
    capture.addEventListener("mouseleave", () => { tooltip.hidden = true; });
    svg.addEventListener("dblclick", () => { domain = fullDomain(); draw(); });
    svg.addEventListener("wheel", (event) => {
      event.preventDefault();
      const factor = event.deltaY > 0 ? 1.15 : 0.87;
      const point = toLocal(event);
      const cx = ux(point.x), cy = uy(point.y);
      domain = { xMin: cx - (cx - domain.xMin) * factor, xMax: cx + (domain.xMax - cx) * factor, yMin: cy - (cy - domain.yMin) * factor, yMax: cy + (domain.yMax - cy) * factor };
      draw();
    }, { passive: false });
    if (resetButton) resetButton.addEventListener("click", () => { domain = fullDomain(); draw(); });
    container.querySelectorAll(".legend-item").forEach((button) => button.addEventListener("click", () => { const label = button.dataset.label; if (hidden.has(label)) hidden.delete(label); else hidden.add(label); draw(); }));
  }

  draw();
}

function unlockedStep() { if (!state.sessionId || !state.mapping || !state.mapping.ready) return 0; if (!state.calibration) return 1; if (!state.calibration.used) return 2; if (!state.treatment) return 3; if (!state.simulation) return 4; return 5; }
function renderTabs() { $("#tabs").innerHTML = stages.map((name, index) => `<button class="tab ${index === state.step ? "active" : ""} ${index > unlockedStep() ? "locked" : ""}" data-step="${index}"><span class="tab-number">${String(index + 1).padStart(2, "0")}</span>${name}</button>`).join(""); document.querySelectorAll(".tab").forEach((button) => button.addEventListener("click", () => { const step = Number(button.dataset.step); if (step <= unlockedStep()) { state.step = step; render(); } })); }
function setHeader() { const stageKicker = $("#stage-kicker"), pageTitle = $("#page-title"), sessionLabel = $("#session-label"); if (!stageKicker || !pageTitle || !sessionLabel) return; stageKicker.textContent = `STEP ${String(state.step + 1).padStart(2, "0")} / 06`; pageTitle.textContent = ["Import your data", "Configure calibration", "Review results", "Fit treatment", "Test protocols", "Export work"][state.step]; sessionLabel.textContent = state.sessionId ? `Session ${state.sessionId}` : "No session"; }
function validationMarkup(mapping) { const invalid = (mapping.subjects || []).filter((subject) => !subject.ok && !subject.excluded); return invalid.length ? `<section class="panel validation-panel"><span class="eyebrow">VALIDATION</span><h2>Subjects to fix.</h2><p class="muted">These subjects remain visible but cannot enter calibration until they are fixed or excluded.</p><div class="table-wrap"><table><thead><tr><th>Subject</th><th>Group</th><th>Points</th><th>Issues</th></tr></thead><tbody>${invalid.map((subject) => `<tr><td>${esc(subject.id)}</td><td>${esc(subject.group)}</td><td>${subject.n_points}</td><td>${esc((subject.why || []).join("; "))}</td></tr>`).join("")}</tbody></table></div></section>` : ""; }
function render() { renderTabs(); setHeader(); $("#app-view").innerHTML = [dataView, calibrationView, resultsView, treatmentView, experimentsView, reportView][state.step](); if (state.step === 0 && state.mapping?.subjects) $("#app-view").insertAdjacentHTML("beforeend", validationMarkup(state.mapping)); if (state.step === 1) $("#calibration-form").insertAdjacentHTML("beforeend", '<button id="cancel-calibration" class="button cancel-button" type="button" hidden>Cancel job</button>'); if (state.step === 2 && state.calibration) $("#app-view .panel").insertAdjacentHTML("beforeend", fitGridMarkup(state.calibration)); wireCurrent(); mountCharts(); }
function mountCharts() { if (state.step === 0 && state.mapping?.subjects?.length) rawCurvesChart(); if (state.step === 2 && state.calibration) { mountFitGridCharts(state.calibration); residualsChart(state.calibration); } if (state.step === 3) { if (state.treatmentMapping?.subjects?.length) treatmentDataChart(state.treatmentMapping); if (state.treatment) treatmentFitCharts(state.treatment); } if (state.step === 4 && state.simulation) mountExperimentChart(state.simulation); }

function welcomeExtras() {
  return `<button id="load-example" class="button secondary" type="button">Load example data</button><ol class="howto"><li><b>Import</b> one table with all animals, or one file per animal (several files at once is fine).</li><li><b>Quick analysis</b> gives a first ranking of the growth laws in seconds, or set the mapping and calibration yourself.</li><li><b>Choose</b> the best law, fit the treatment effect, then test dosing protocols.</li></ol><p class="muted">Everything runs on this computer: your data never leaves it.</p>`;
}
const fileSummary = (upload) => ((upload.filenames || []).length > 1 ? `${upload.filenames.length} files loaded` : upload.filename);
function uploadExtras(upload) {
  const names = upload.filenames || [], warnings = upload.warnings || [], guess = upload.mapping_guess || {};
  const canQuick = Boolean(guess.time && guess.volume);
  const short = names.slice(0, 3).map((name) => name.split("/").pop()).join(", ") + (names.length > 3 ? ", …" : "");
  const list = names.length > 1 ? `<details class="file-list"><summary>${names.length} files: ${esc(short)}</summary><p class="muted">${names.map(esc).join("<br>")}</p></details>` : "";
  const warn = warnings.length ? `<div class="notice warning"><b>${warnings.length} file(s) need attention</b><br>${warnings.map(esc).join("<br>")}</div>` : "";
  const hint = canQuick ? `Uses <code>${esc(guess.time)}</code> as time and <code>${esc(guess.volume)}</code> as volume, all seven laws, 1 start. Good for a first look: rerun with more starts in the Calibration tab to confirm.` : "Time/volume columns could not be detected automatically. Use the mapping form below.";
  return `${list}${warn}<button id="quick-analysis" class="button" type="button" ${canQuick ? "" : "disabled"}>Quick analysis</button><p class="muted quick-hint">${hint}</p><div id="quick-status"></div>`;
}
// One click from "files uploaded" to "ranked growth laws": validate with the detected columns, then calibrate.
async function quickAnalysis() {
  const guess = state.upload?.mapping_guess || {};
  if (!guess.time || !guess.volume) { alert("Time/volume columns could not be detected. Use the mapping form."); return; }
  const button = $("#quick-analysis"), status = $("#quick-status");
  button.disabled = true; button.textContent = "Analysing…";
  try {
    state.mapping = await api("/api/datasets/mapping", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_id: state.sessionId, mapping: { time: guess.time, volume: guess.volume, subject: guess.subject || null, group: guess.group || null }, control_group: "control", time_unit: "days", volume_unit: "mm3", exclude_subjects: [] }) });
    if (!state.mapping.ready) { state.step = 0; render(); return; }
    if (status) status.innerHTML = '<p class="muted">Data validated, starting calibration…</p>';
    const job = await api("/api/calibration", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId, models: ["exponential", "mendelsohn", "logistic", "bertalanffy", "gompertz", "linear", "surface"], starts: 1, maxiter: 250, seed: 42, selection_metric: "bic", t0_strategy: "free", count_t0_in_ic: true }) });
    state.calibration = await pollCalibration(job.job_id);
    localStorage.setItem("tumor-fit-session", state.sessionId);
    state.step = 2; render();
  } catch (error) { alert(error.message); const again = $("#quick-analysis"); if (again) { again.disabled = false; again.textContent = "Quick analysis"; } }
}
function ignoredNotice() {
  const ignored = (state.mapping?.subjects || []).filter((subject) => !subject.ok && !subject.excluded);
  const analysed = state.calibration?.ranking?.[0]?.curves?.length ?? 0;
  const detail = ignored.length ? `; <b>${ignored.length} ignored</b>: ${ignored.map((subject) => `${esc(subject.id)} (${esc((subject.why || []).join(", "))})`).join("; ")}` : "";
  return `<div class="notice ${ignored.length ? "warning" : ""}">${analysed} subject(s) analysed${detail}.</div>`;
}
function dataView() { const upload = state.upload; const columns = upload?.columns || []; const guess = upload?.mapping_guess || {}; return `<div class="grid"><section class="panel"><span class="eyebrow">01 / SOURCE</span><h2>Your curve, your rules.</h2><p class="muted">CSV/XLSX, long or wide format. The mapping can be edited before analysis.</p><label class="dropzone"><strong>${upload ? esc(fileSummary(upload)) : "Drop one or more files here, or click"}</strong><span>${upload ? "File ready for mapping" : "CSV, XLSX · local data only"}</span><input id="file-input" type="file" accept=".csv,.xlsx,.xls"></label>${upload ? uploadExtras(upload) : welcomeExtras()}${upload ? `<form id="mapping-form">${select("Time", "time", guess.time, columns)}${select("Volume", "volume", guess.volume, ["(wide format)", ...columns])}${select("Subject", "subject", guess.subject, ["(one subject only)", ...columns])}${select("Group", "group", guess.group, ["(one group only)", ...columns])}${select("Time unit", "time_unit", "days", ["days", "hours"])}${select("Volume unit", "volume_unit", "mm3", ["mm3", "cm3"])}<div class="field"><label>Control group</label><input name="control" value="control"></div><div class="field"><label>Subjects to exclude</label><input name="exclude" placeholder="m3,m7"></div><button class="button" type="submit">Validate data →</button></form>` : ""}</section><section class="panel"><div class="preview-head"><div><span class="eyebrow">PREVIEW</span><h2>Instant preview</h2></div>${upload ? `<span class="tag">${upload.columns.length} columns</span>` : ""}</div>${upload ? `<div class="table-wrap"><table><thead><tr>${upload.columns.map((column) => `<th>${esc(column)}</th>`).join("")}</tr></thead><tbody>${upload.rows.map((row) => `<tr>${upload.columns.map((column) => `<td>${esc(row[column])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : '<div class="empty"><p>The table will appear here.</p></div>'}${state.mapping?.subjects?.length ? `<div class="chart-mount" id="raw-curves-chart"></div>` : ""}</section></div>`; }
function rawCurvesChart() { const subjects = (state.mapping?.subjects || []).filter((subject) => (subject.t || []).length); const series = subjects.map((subject, index) => ({ label: `${subject.id} (${subject.group})`, color: colorFor(index), points: subject.t.map((t, pointIndex) => [t, subject.v[pointIndex]]), dashed: !subject.ok || subject.excluded, opacity: !subject.ok || subject.excluded ? 0.55 : 1 })); mountChart($("#raw-curves-chart"), series, { title: "Raw curves by subject - each subject has a distinct color", ariaLabel: "Raw volume curves by subject", xLabel: "day", yLabel: "volume", legend: series.length <= 14 }); }
function calibrationView() { return `<div class="grid"><section class="panel"><span class="eyebrow">02 / FIT</span><h2>Compare growth laws.</h2><p class="muted">Growth is fitted on the control group, with one T0 per subject.</p><form id="calibration-form"><div class="field"><label>Models to compare</label><div class="model-options">${["exponential", "mendelsohn", "logistic", "bertalanffy", "gompertz", "linear", "surface"].map((model) => `<label><input type="checkbox" name="models" value="${model}" checked> ${model}</label>`).join("")}</div></div><div class="field"><label>T0 strategy</label><select name="t0_strategy"><option value="free">Free: 0.10× to 4×</option><option value="fixed_first_obs">Fixed at first point</option><option value="narrow_first_obs">Narrow: ±10%</option></select></div><div class="field"><label>Criterion</label><select name="selection_metric"><option value="bic">BIC</option><option value="aicc">AICc</option></select></div><div class="field"><label>Number of starts</label><input name="starts" type="number" min="1" max="20" value="3"></div><div class="field"><label>Maximum iterations</label><input name="maxiter" type="number" min="50" max="2000" value="250"></div><div class="field"><label>Seed</label><input name="seed" type="number" value="42"></div><div class="notice">The progress bar follows the local job, law by law and start by start. With 1 or 2 starts the result is for exploration: use 6 to 8 starts for a result worth keeping.</div><button class="button" type="submit">Run calibration →</button></form></section><section class="panel"><span class="eyebrow">JOB STATUS</span><h2 id="job-title">Ready.</h2><div id="calibration-status" class="empty"><p>Seven models available, ranked by BIC.</p></div></section></div>`; }
function fitGridMarkup(result) { const curves = result.ranking[0]?.curves || []; const card = (curve, index) => `<div class="chart-mount" id="fit-chart-${index}"><div class="fit-card-head"><b>${esc(curve.subject)}</b><span>${esc(curve.group)}</span></div></div>`; return curves.length ? `<div class="fit-section"><div class="preview-head"><div><span class="eyebrow">FIT GRID</span><h3>Curves by subject</h3></div><span class="tag">${curves.length} subjects</span></div><div class="fit-grid-interactive">${curves.map(card).join("")}</div></div>` : ""; }
function mountFitGridCharts(result) { const curves = result.ranking[0]?.curves || []; curves.forEach((curve, index) => { const series = [{ label: "Observed", color: colorFor(0), points: curve.t.map((t, i) => [t, curve.observed[i]]), style: "points" }, { label: "Fitted", color: colorFor(1), points: curve.t.map((t, i) => [t, curve.fitted[i]]), dashed: true }]; mountChart($(`#fit-chart-${index}`), series, { width: 320, height: 200, ariaLabel: `Fit for subject ${curve.subject}`, xLabel: "day", yLabel: "volume", legend: false }); }); }
function diagnosticsCell(row) { const items = row.diagnostics || []; return items.length ? `<span title="${esc(items.join("; "))}">⚠ ${items.length}</span>` : "-"; }
function residualsChart(result) { const curves = result.ranking[0]?.curves || []; const series = curves.map((curve, index) => ({ label: `${curve.subject} (${curve.group})`, color: colorFor(index), points: curve.t.map((t, pointIndex) => [t, curve.observed[pointIndex] - curve.fitted[pointIndex]]), style: "points" })); mountChart($("#residuals-chart"), series, { title: `Residuals (observed - fitted) for ${result.ranking[0].model} - each subject has a distinct color`, ariaLabel: "Residuals over time", xLabel: "day", yLabel: "residual", zeroLine: 0, symmetricY: true, legend: series.length <= 14 }); }
function resultsView() { const result = state.calibration; if (!result) return `<section class="panel empty"><p>Run a calibration first.</p></section>`; const sentence = result.tie_with.length ? `<b>${esc(result.winner)}</b> wins, but ${result.tie_with.map(esc).join(", ")} is within a ΔBIC of 2: the data do not clearly separate them.` : `<b>${esc(result.winner)}</b> wins clearly; no other model is within 2 BIC points.`; return `<section class="panel"><div class="preview-head"><div><span class="eyebrow">03 / RANKING</span><h2>What the data say.</h2></div><span class="tag">${esc((result.selection_metric || "bic").toUpperCase())} · Δ &lt; 2 = tie</span></div><div class="metric-row"><div class="metric"><small>Selected model</small><strong class="winner">${esc(result.winner)}</strong></div><div class="metric"><small>Ties (ΔBIC &lt; 2)</small><strong>${result.tie_with.length ? result.tie_with.join(", ") : "None"}</strong></div><div class="metric"><small>T0 strategy</small><strong>${esc(result.t0_strategy || "free")}</strong></div></div><div class="notice">${sentence}</div>${ignoredNotice()}<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Law</th><th>BIC</th><th>AICc</th><th>ΔBIC</th><th>Akaike weight</th><th>RMSE</th><th>Last point (MAE)</th><th>T0 bounds</th><th>Action</th></tr></thead><tbody>${result.ranking.map((row, index) => `<tr><td>${index + 1}</td><td><b>${esc(row.model)}</b></td><td>${row.metrics.bic.toFixed(2)}</td><td>${row.metrics.aicc.toFixed(2)}</td><td>${row.delta_bic.toFixed(2)}</td><td>${(row.akaike_weight * 100).toFixed(1)}%</td><td>${row.metrics.rmse.toFixed(3)}</td><td>${row.validation?.enabled ? row.validation.mae.toFixed(3) : "-"}</td><td>${diagnosticsCell(row)}</td><td><button class="button secondary use-model" data-model="${esc(row.model)}" type="button">Use</button></td></tr>`).join("")}</tbody></table></div><div class="chart-mount" id="residuals-chart"></div></section>`; }
function treatmentDataChart(result) {
  const subjects = result.subjects || [];
  const groups = [...new Set(subjects.map((subject) => subject.group))];
  const series = subjects.filter((subject) => (subject.t || []).length).map((subject) => ({
    label: `${subject.id} (${subject.group})`,
    color: colorFor(groups.indexOf(subject.group)),
    points: subject.t.map((time, index) => [time, subject.v[index]]),
    style: "points",
  }));
  if (series.length) mountChart($("#treatment-data-chart"), series, { title: "Uploaded treatment observations", ariaLabel: "Uploaded treatment observations", legend: series.length <= 14 });
}
function treatmentUploadPanelMarkup() {
  const upload = state.treatmentUpload;
  if (!upload) return `<section class="panel"><span class="eyebrow">TREATMENT DATA</span><h2>Upload treatment observations.</h2><p class="muted">Add the treated-animal CSV/XLSX separately from the growth data. Each subject needs at least four time and volume observations.</p><label class="dropzone"><strong>Drop one or more treatment files here, or click</strong><span>CSV, XLSX · local data only</span><input id="treatment-file-input" type="file" accept=".csv,.xlsx,.xls" multiple></label><div id="treatment-upload-status"></div></section>`;
  const columns = upload.columns || [];
  const guess = upload.mapping_guess || {};
  const validation = (state.treatmentMapping?.subjects || []).filter((subject) => !subject.ok);
  const preview = `<div class="table-wrap"><table><thead><tr>${columns.map((column) => `<th>${esc(column)}</th>`).join("")}</tr></thead><tbody>${(upload.rows || []).map((row) => `<tr>${columns.map((column) => `<td>${esc(row[column])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const mappingForm = state.treatmentMapping?.ready
    ? `<div class="notice">${state.treatmentMapping.subjects.length - validation.length} valid treatment subject(s) mapped${validation.length ? `; ${validation.length} subject(s) ignored: ${validation.map((subject) => `${esc(subject.id)} (${esc((subject.why || []).join(", "))})`).join("; ")}` : ""}.</div><div class="chart-mount" id="treatment-data-chart"></div>`
    : `<form id="treatment-mapping-form">${select("Time", "time", guess.time, columns)}${select("Volume", "volume", guess.volume, ["(wide format)", ...columns])}${select("Subject", "subject", guess.subject, ["(one subject only)", ...columns])}${select("Group", "group", guess.group, ["(one group only)", ...columns])}${select("Time unit", "time_unit", "days", ["days", "hours"])}${select("Volume unit", "volume_unit", "mm3", ["mm3", "cm3"])}<div class="field"><label>Default group</label><input name="default_group" value="treatment"></div><button class="button" type="submit">Validate treatment data →</button></form>`;
  return `<section class="panel validation-panel"><div class="preview-head"><div><span class="eyebrow">TREATMENT DATA</span><h2>${esc(upload.filename || "Treatment upload")}</h2></div><button class="button secondary" id="replace-treatment-data" type="button" aria-label="Replace treatment data">↻</button></div><p class="muted">${(upload.filenames || []).length} file(s) uploaded separately from the growth data. Map the columns before fitting.</p>${preview}${mappingForm}</section>`;
}
function treatmentView() {
  const treatment = state.treatment;
  const noneBeaten = treatment ? treatment.winner !== "none" : null;
  const groups = state.treatmentMapping?.groups || [];
  const resultsPanel = !treatment
    ? `<div class="notice">The <code>none</code> model is always included as a reference.</div>`
    : `<div class="notice">${noneBeaten ? `<b>${esc(treatment.winner)}</b> explains the uploaded treatment data better than no treatment (lower BIC than <code>none</code>).` : `No treatment term explained the uploaded data better than <code>none</code>: check the dose schedule before concluding there is an effect.`}</div>
      <div class="table-wrap"><table><thead><tr><th>Rank</th><th>Term</th><th>BIC</th><th>ΔBIC</th></tr></thead><tbody>${treatment.ranking.map((row, index) => `<tr><td>${index + 1}</td><td><b>${esc(row.model)}</b></td><td>${row.metrics.bic.toFixed(2)}</td><td>${row.delta_bic.toFixed(2)}</td></tr>`).join("")}</tbody></table></div>
      <div class="treatment-chart-grid">${treatment.ranking.map((row, index) => `<section class="metric"><b>${index + 1}. ${esc(row.model)}</b><div class="chart-mount" id="treatment-fit-chart-${index}"></div></section>`).join("")}</div>`;
  return `${treatmentUploadPanelMarkup()}<div class="grid"><section class="panel"><span class="eyebrow">04 / TREATMENT</span><h2>Fit treatment.</h2><p class="muted">The winning growth law stays fixed. Every treatment term is fitted against the separately uploaded observations.</p><form id="treatment-form">${select("Treated group", "treated_group", groups[0] || "", groups)}${select("Term", "model", "ED", treatmentModels)}<div id="treatment-equation" class="notice">${esc(treatmentEquations.ED)}<br><small>For the five time-dependent terms, s = max(t − first treatment day, 0); dose sizes do not enter these equations.</small></div><div class="field"><label>Dose days</label><input name="days" value="7,14,21"></div><div class="field"><label>Doses</label><input name="doses" value="1,1,1"></div><div class="field"><label>Starts</label><input name="starts" type="number" min="1" max="20" value="3"></div><button class="button" type="submit" ${state.treatmentMapping?.ready ? "" : "disabled"}>Compare treatments →</button></form></section><section class="panel"><span class="eyebrow">GROWTH FIXED</span><h2>${esc(state.calibration?.winner || "-")}</h2><div id="treatment-status" class="empty"><p>Twelve terms available, ranked by BIC.</p></div>${resultsPanel}</section></div>`;
}
function treatmentFitCharts(result) {
  (result.ranking || []).forEach((row, index) => {
    const curves = row.curves || [];
    const groups = [...new Set(curves.map((curve) => curve.group))];
    const series = curves.flatMap((curve) => {
      const color = colorFor(groups.indexOf(curve.group));
      const subject = `${curve.subject} (${curve.group})`;
      return [
        { label: `Observed · ${subject}`, color, points: curve.t.map((time, point) => [time, curve.observed[point]]), style: "points" },
        { label: `Fitted · ${subject}`, color, points: curve.t.map((time, point) => [time, curve.fitted[point]]), dashed: true },
      ];
    });
    if (series.length) mountChart($(`#treatment-fit-chart-${index}`), series, {
      title: `${row.model} — observed vs fitted`,
      ariaLabel: `Observed and fitted treatment curve for ${row.model}`,
      legend: curves.length <= 7,
    });
  });
}
function scenarioRowMarkup(scenario, index) { return `<div class="scenario-row"><div class="field"><label>Name</label><input name="name" value="${esc(scenario.name)}"></div><div class="field"><label>Days</label><input name="days" value="${esc(scenario.days)}"></div><div class="field"><label>Doses</label><input name="doses" value="${esc(scenario.doses)}"></div>${index === 0 ? '<button class="button secondary" type="button" id="add-scenario" aria-label="Add scenario">+</button>' : `<button class="button secondary" type="button" data-remove-scenario="${index}" aria-label="Remove scenario">−</button>`}</div>`; }
function experimentsView() { return `<div class="grid"><section class="panel"><span class="eyebrow">05 / SCENARIOS</span><h2>Test the next experiment.</h2><form id="experiment-form"><div class="metric-row experiment-settings"><div class="field"><label>Initial volume (mm³)</label><input name="initial_volume" type="number" min="0.0001" step="0.01" value="0.8"></div><div class="field"><label>Horizon (days)</label><input name="horizon_days" type="number" min="1" step="1" value="60"></div><div class="field"><label>Simulation points</label><input name="n_points" type="number" min="20" max="2000" step="10" value="240"></div></div><div class="generator"><span class="eyebrow">GENERATOR</span><div class="generator-fields"><input id="generator-name" placeholder="Protocol name" value="Generated protocol"><input id="generator-count" type="number" min="1" value="3" placeholder="Number of doses"><input id="generator-start" type="number" min="0" value="7" placeholder="First day"><input id="generator-interval" type="number" min="0.1" value="7" placeholder="Interval (days)"><input id="generator-dose" type="number" min="0" step="0.1" value="1" placeholder="Dose"><button class="button secondary" type="button" id="generate-scenario">Generate</button></div></div><div id="scenario-list">${state.scenarios.map(scenarioRowMarkup).join("")}</div><button class="button" type="submit">Simulate scenarios →</button></form></section><section class="panel"><span class="eyebrow">OUTCOMES</span><h2>Projected curves.</h2><div id="simulation-status" class="empty"><p>${state.simulation ? "Simulation complete." : "Add a scenario to display the projection."}</p></div>${state.simulation ? `<div class="chart-mount" id="experiment-chart"></div><div class="metric-row">${experimentOutcomesMarkup(state.simulation)}</div>` : ""}</section></div>`; }
function experimentOutcomesMarkup(result) { return `<div class="metric"><small>Final control</small><strong>${result.control.at(-1).toFixed(2)}</strong></div>${result.scenarios.map((scenario) => `<div class="metric"><small>${esc(scenario.name)}</small><strong class="winner">${scenario.tgi_pct.toFixed(1)}% TGI</strong></div>`).join("")}`; }
function mountExperimentChart(result) { const series = [{ label: "Simulated control", color: "#7d817d", dashed: true, points: result.t.map((t, index) => [t, result.control[index]]) }, ...result.scenarios.map((scenario, index) => ({ label: scenario.name, color: colorFor(index + 2), points: result.t.map((t, i) => [t, scenario.values[i]]) }))]; mountChart($("#experiment-chart"), series, { title: "Projected volumes", ariaLabel: "Projected simulated volumes", xLabel: "day", yLabel: "volume" }); }
function reportView() { return `<section class="panel"><span class="eyebrow">06 / REPORT</span><h2>Provenance trail.</h2><p class="muted">ZIP with ranking, parameters, curves, scenarios, text report and PNG charts.</p><div class="metric-row"><div class="metric"><small>Session</small><strong>${esc(state.sessionId || "-")}</strong></div><div class="metric"><small>Model</small><strong>${esc(state.calibration?.winner || "-")}</strong></div><div class="metric"><small>Scenarios</small><strong>${state.simulation?.scenarios.length || 0}</strong></div></div><button id="download-report" class="button">Download ZIP →</button></section>`; }

async function pollCalibration(jobId) { let status; do { await new Promise((resolve) => setTimeout(resolve, 200)); status = await api(`/api/jobs/${jobId}`); const pct = status.n_steps ? Math.round((100 * status.step) / status.n_steps) : 0; const jobTitle = $("#job-title"), calibrationStatus = $("#calibration-status"); const quickStatus = $("#quick-status"); if (quickStatus) quickStatus.innerHTML = `<div><p class="muted">${esc(status.stage || "calibration")} · ${status.step || 0} / ${status.n_steps || "?"}</p><div class="progress"><i style="width:${pct}%"></i></div></div>`; if (jobTitle) jobTitle.textContent = `Job ${status.status} - ${pct}%`; if (calibrationStatus) calibrationStatus.innerHTML = `<div><p>${esc(status.stage || "calibration")}</p><p class="muted">${status.step || 0} / ${status.n_steps || "?"} adjustments (law × start)</p><div class="progress"><i style="width:${pct}%"></i></div></div>`; } while (status.status === "queued" || status.status === "running"); if (status.status !== "done") throw new Error(status.error || (status.status === "cancelled" ? "Calibration was cancelled" : "Calibration failed")); return status.result; }
async function pollJob(jobId, target, label) { let status; do { await new Promise((resolve) => setTimeout(resolve, 200)); status = await api(`/api/jobs/${jobId}`); const pct = status.n_steps ? Math.round((100 * status.step) / status.n_steps) : 0; const targetElement = $(target); if (targetElement) targetElement.innerHTML = `<div><p>${esc(status.stage || label)}</p><p class="muted">${status.step || 0} / ${status.n_steps || "?"} steps</p><div class="progress"><i style="width:${pct}%"></i></div></div>`; } while (status.status === "queued" || status.status === "running"); if (status.status !== "done") throw new Error(status.error || `${label} failed`); return status.result; }
function wireCurrent() {
  const fileInput = $("#file-input");
  if (fileInput) { const uploadFiles = async (files) => { const form = new FormData(); [...files].filter((file) => /\.(csv|xlsx?|xls)$/i.test(file.name)).forEach((file) => form.append("file", file)); if (!form.has("file")) { alert("Select at least one CSV or XLSX file"); return; } try { state.upload = await api("/api/datasets/upload", { method: "POST", body: form }); state.sessionId = state.upload.source_id; localStorage.setItem("tumor-fit-session", state.sessionId); render(); } catch (error) { alert(error.message); } }; fileInput.multiple = true; fileInput.addEventListener("change", () => uploadFiles(fileInput.files)); const dropzone = fileInput.closest(".dropzone"); ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("drag-over"); })); ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, () => dropzone.classList.remove("drag-over"))); dropzone.addEventListener("drop", (event) => { event.preventDefault(); if (event.dataTransfer?.files?.length) uploadFiles(event.dataTransfer.files); }); const folderInput = document.createElement("input"); folderInput.type = "file"; folderInput.multiple = true; folderInput.hidden = true; folderInput.setAttribute("webkitdirectory", ""); folderInput.setAttribute("directory", ""); folderInput.addEventListener("change", () => uploadFiles(folderInput.files)); const folderButton = document.createElement("button"); folderButton.type = "button"; folderButton.className = "button secondary folder-upload"; folderButton.textContent = "Select folder"; folderButton.addEventListener("click", () => folderInput.click()); fileInput.closest(".dropzone").insertAdjacentElement("afterend", folderButton); fileInput.closest(".dropzone").appendChild(folderInput); }
  const exampleButton = $("#load-example");
  if (exampleButton) exampleButton.addEventListener("click", async () => { try { state.upload = await api("/api/datasets/upload-folder", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ directory: "examples/frosberg_fig3D" }) }); state.sessionId = state.upload.source_id; localStorage.setItem("tumor-fit-session", state.sessionId); render(); } catch (error) { alert(error.message); } });
  const quickButton = $("#quick-analysis"); if (quickButton) quickButton.addEventListener("click", quickAnalysis);
  const mappingForm = $("#mapping-form");
  if (mappingForm) mappingForm.addEventListener("submit", async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(mappingForm)); try { state.mapping = await api("/api/datasets/mapping", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_id: state.sessionId, mapping: { time: values.time, volume: values.volume.startsWith("(") ? null : values.volume, subject: values.subject.startsWith("(") ? null : values.subject, group: values.group.startsWith("(") ? null : values.group }, control_group: values.control, time_unit: values.time_unit, volume_unit: values.volume_unit, exclude_subjects: values.exclude.split(",").map((item) => item.trim()).filter(Boolean) }) }); localStorage.setItem("tumor-fit-session", state.sessionId); state.step = state.mapping.ready ? 1 : 0; render(); } catch (error) { alert(error.message); } });
  const treatmentFileInput = $("#treatment-file-input");
  if (treatmentFileInput) {
    const uploadTreatmentFiles = async (files) => {
      const form = new FormData();
      form.append("session_id", state.sessionId);
      [...files].filter((file) => /\.(csv|xlsx?|xls)$/i.test(file.name)).forEach((file) => form.append("file", file));
      if (!form.has("file")) { alert("Select at least one CSV or XLSX treatment file"); return; }
      try {
        state.treatmentUpload = await api("/api/treatment-data/upload", { method: "POST", body: form });
        state.treatmentMapping = null;
        state.treatment = null;
        render();
      } catch (error) { alert(error.message); }
    };
    const dropzone = treatmentFileInput.closest(".dropzone");
    treatmentFileInput.addEventListener("change", () => uploadTreatmentFiles(treatmentFileInput.files));
    ["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => { event.preventDefault(); dropzone.classList.add("drag-over"); }));
    ["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, () => dropzone.classList.remove("drag-over")));
    dropzone.addEventListener("drop", (event) => { event.preventDefault(); if (event.dataTransfer?.files?.length) uploadTreatmentFiles(event.dataTransfer.files); });
  }
  const replaceTreatmentData = $("#replace-treatment-data");
  if (replaceTreatmentData) replaceTreatmentData.addEventListener("click", () => { state.treatmentUpload = null; state.treatmentMapping = null; state.treatment = null; render(); });
  const treatmentMappingForm = $("#treatment-mapping-form");
  if (treatmentMappingForm) treatmentMappingForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(treatmentMappingForm));
    try {
      state.treatmentMapping = await api("/api/treatment-data/mapping", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: state.sessionId,
          mapping: {
            time: values.time,
            volume: values.volume.startsWith("(") ? null : values.volume,
            subject: values.subject.startsWith("(") ? null : values.subject,
            group: values.group.startsWith("(") ? null : values.group,
          },
          default_group: values.default_group,
          time_unit: values.time_unit,
          volume_unit: values.volume_unit,
        }),
      });
      state.treatment = null;
      render();
    } catch (error) { alert(error.message); }
  });
  const calibrationForm = $("#calibration-form");
  if (calibrationForm) calibrationForm.addEventListener("submit", async (event) => { event.preventDefault(); const values = Object.fromEntries(new FormData(calibrationForm)); const models = [...calibrationForm.querySelectorAll('[name="models"]:checked')].map((input) => input.value); if (!models.length) { alert("Select at least one growth law"); return; } try { const job = await api("/api/calibration", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId, models, starts: Number(values.starts), maxiter: Number(values.maxiter), seed: Number(values.seed), selection_metric: values.selection_metric, t0_strategy: values.t0_strategy, count_t0_in_ic: true }) }); const cancelButton = $("#cancel-calibration"); cancelButton.hidden = false; cancelButton.addEventListener("click", () => api(`/api/jobs/${job.job_id}/cancel`, { method: "POST" })); state.calibration = await pollCalibration(job.job_id); state.step = 2; render(); } catch (error) { alert(error.message); } });
  document.querySelectorAll(".use-model").forEach((button) => button.addEventListener("click", async () => { try { await api("/api/calibration/select", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId, model: button.dataset.model }) }); const selected = state.calibration.ranking.find((row) => row.model === button.dataset.model); state.calibration.ranking = [selected, ...state.calibration.ranking.filter((row) => row.model !== button.dataset.model)]; state.calibration.winner = button.dataset.model; state.calibration.used = true; state.step = 3; render(); } catch (error) { alert(error.message); } }));
  const treatmentForm = $("#treatment-form");
  const treatmentModel = treatmentForm?.querySelector('[name="model"]');
  if (treatmentModel) treatmentModel.addEventListener("change", () => { $("#treatment-equation").firstChild.textContent = treatmentEquations[treatmentModel.value]; });
  if (treatmentForm) treatmentForm.addEventListener("submit", async (event) => { event.preventDefault(); try { const values = Object.fromEntries(new FormData(treatmentForm)); const days = values.days.split(",").map((item) => Number(item.trim())); const doses = values.doses.split(",").map((item) => Number(item.trim())); if (!days.length || days.length !== doses.length || days.some(Number.isNaN) || doses.some(Number.isNaN)) throw new Error("Days and doses must have the same number of numeric values, separated by commas."); const job = await api("/api/treatment", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId, treated_group: values.treated_group || null, doses: days.map((day, index) => [day, doses[index]]), starts: Number(values.starts) }) }); state.treatment = await pollJob(job.job_id, "#treatment-status", "treatment"); state.treatment.selected_model = values.model; state.step = 3; render(); } catch (error) { alert(error.message); } });
  const experimentForm = $("#experiment-form");   if (experimentForm) experimentForm.addEventListener("submit", async (event) => { event.preventDefault(); try { const values = Object.fromEntries(new FormData(experimentForm)); const scenarios = [...document.querySelectorAll(".scenario-row")].map((row) => ({ name: row.querySelector('[name="name"]').value, days: row.querySelector('[name="days"]').value, doses: row.querySelector('[name="doses"]').value, dose_times: row.querySelector('[name="days"]').value.split(",").map((item) => Number(item.trim())), dose_values: row.querySelector('[name="doses"]').value.split(",").map((item) => Number(item.trim())) })); const invalid = scenarios.find((scenario) => !scenario.dose_times.length || scenario.dose_times.length !== scenario.dose_values.length || scenario.dose_times.some(Number.isNaN) || scenario.dose_values.some(Number.isNaN)); if (invalid) throw new Error(`Scenario "${invalid.name}" has invalid days/doses or lists of different lengths.`); state.scenarios = scenarios.map(({ name, days, doses }) => ({ name, days, doses })); const selectedModel = state.treatment?.selected_model || state.treatment?.winner || "ED"; const selectedTreatment = state.treatment?.ranking?.find((row) => row.model === selectedModel); const job = await api("/api/experiments/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: state.sessionId, initial_volume: Number(values.initial_volume), horizon_days: Number(values.horizon_days), n_points: Number(values.n_points), treatment_model: selectedModel, treatment_params: selectedTreatment?.params || { a: 0.2, b: 0.1 }, scenarios: scenarios.map(({ name, dose_times, dose_values }) => ({ name, dose_times, doses: dose_values })) }) }); state.simulation = await pollJob(job.job_id, "#simulation-status", "simulation"); render(); } catch (error) { alert(error.message); } });
  const generateScenario = $("#generate-scenario"); if (generateScenario) generateScenario.addEventListener("click", () => { const count = Number($("#generator-count").value); const start = Number($("#generator-start").value); const interval = Number($("#generator-interval").value); const dose = Number($("#generator-dose").value); const name = $("#generator-name").value.trim() || `Protocol ${String.fromCharCode(65 + state.scenarios.length)}`; state.scenarios = [...document.querySelectorAll(".scenario-row")].map((row) => ({ name: row.querySelector('[name="name"]').value, days: row.querySelector('[name="days"]').value, doses: row.querySelector('[name="doses"]').value })); state.scenarios.push({ name, days: Array.from({ length: count }, (_, index) => (start + index * interval).toString()).join(","), doses: Array.from({ length: count }, () => dose).join(",") }); render(); });
  const scenarioRows = () => [...document.querySelectorAll(".scenario-row")].map((row) => ({ name: row.querySelector('[name="name"]').value, days: row.querySelector('[name="days"]').value, doses: row.querySelector('[name="doses"]').value }));
  const addScenario = $("#add-scenario"); if (addScenario) addScenario.addEventListener("click", () => { state.scenarios = scenarioRows(); state.scenarios.push({ name: `Protocol ${String.fromCharCode(65 + state.scenarios.length)}`, days: "7,21", doses: "0.7,0.7" }); render(); });
  document.querySelectorAll("[data-remove-scenario]").forEach((button) => button.addEventListener("click", () => { state.scenarios = scenarioRows().filter((_, index) => index !== Number(button.dataset.removeScenario)); render(); }));
  const download = $("#download-report"); if (download) download.addEventListener("click", () => { window.location.href = `/api/export/${encodeURIComponent(state.sessionId)}`; });
}

const themeToggle = $("#theme-toggle");
const savedTheme = localStorage.getItem("tumor-fit-theme");
if (savedTheme === "dark") document.documentElement.classList.add("dark");
function updateThemeLabel() { if (!themeToggle) return; const dark = document.documentElement.classList.contains("dark"); themeToggle.textContent = dark ? "☀" : "☾"; themeToggle.title = dark ? "Enable light mode" : "Enable dark mode"; themeToggle.setAttribute("aria-label", themeToggle.title); }
themeToggle.addEventListener("click", () => { document.documentElement.classList.toggle("dark"); localStorage.setItem("tumor-fit-theme", document.documentElement.classList.contains("dark") ? "dark" : "light"); updateThemeLabel(); });
updateThemeLabel();
render();
async function restoreSession() { const sessionId = localStorage.getItem("tumor-fit-session"); if (!sessionId) return; try { const saved = await api(`/api/sessions/${encodeURIComponent(sessionId)}`); state.sessionId = saved.session_id; state.upload = { source_id: saved.session_id, filename: saved.filename, ...saved.preview }; if (saved.mapping) state.mapping = { ...saved.mapping, groups: saved.groups, control_group: saved.control_group, subjects: saved.validation }; state.calibration = saved.calibration; if (state.calibration) state.calibration.used = Boolean(state.calibration.selected_model); state.treatmentUpload = saved.treatment_upload; if (saved.treatment_upload && saved.treatment_mapping) state.treatmentMapping = { ...saved.treatment_mapping, ready: true, groups: saved.treatment_groups, subjects: saved.treatment_validation }; state.treatment = saved.treatment; state.simulation = saved.simulation; state.step = state.simulation ? 5 : state.treatment ? 3 : state.calibration?.used ? 3 : state.calibration ? 2 : state.mapping ? 1 : 0; render(); } catch { localStorage.removeItem("tumor-fit-session"); } }
restoreSession();
