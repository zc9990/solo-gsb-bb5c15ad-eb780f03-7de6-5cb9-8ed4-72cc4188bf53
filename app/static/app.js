/* 离心机转子配平规划器 — 原生前端逻辑 */
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);

const state = {
  disabled: new Set(),
  result: null,          // 最近一次规划结果
  requestSnapshot: null, // 对应请求
  stepIndex: 0,
  playing: null,
  savedId: null,         // 当前结果对应的历史方案 id（未保存为 null）
};

/* ---------------- 工具 ---------------- */

function fmt(x, d = 2) {
  if (x === null || x === undefined) return "—";
  return Number(x).toLocaleString("zh-CN", {
    minimumFractionDigits: 0, maximumFractionDigits: d,
  });
}

function getAngles() {
  const n = parseInt($("nSlots").value, 10);
  if ($("angleMode").value === "custom") {
    const vals = $("customAngles").value
      .split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean).map(Number);
    if (vals.length === n && vals.every((v) => Number.isFinite(v))) return vals;
    return null;
  }
  return Array.from({ length: n }, (_, i) => 360 * i / n);
}

function el(name, attrs = {}, parent) {
  const e = document.createElementNS(SVGNS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}

/* ---------------- 试管表 ---------------- */

let tubeSeq = 0;
function addTubeRow(id, mass, locked, lockedSlot) {
  tubeSeq += 1;
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input type="text" class="t-id" value="${id || ("T" + tubeSeq)}" style="width:70px"></td>
    <td><input type="number" class="t-mass" value="${mass ?? 10}" min="0" step="0.1" style="width:80px"></td>
    <td><input type="checkbox" class="t-lock" ${locked ? "checked" : ""}></td>
    <td><input type="number" class="t-slot" min="0" value="${lockedSlot ?? ""}"
        style="width:70px" ${locked ? "" : "disabled"} placeholder="槽号"></td>
    <td><button class="row-del" title="删除">✕</button></td>`;
  tr.querySelector(".t-lock").addEventListener("change", (e) => {
    tr.querySelector(".t-slot").disabled = !e.target.checked;
    if (!e.target.checked) tr.querySelector(".t-slot").value = "";
  });
  tr.querySelector(".row-del").addEventListener("click", () => tr.remove());
  $("tubesTable").querySelector("tbody").appendChild(tr);
}

function readTubes() {
  return [...$("tubesTable").querySelectorAll("tbody tr")].map((tr) => {
    const locked = tr.querySelector(".t-lock").checked;
    const slotRaw = tr.querySelector(".t-slot").value;
    return {
      id: tr.querySelector(".t-id").value.trim(),
      mass: parseFloat(tr.querySelector(".t-mass").value),
      locked,
      locked_slot: locked && slotRaw !== "" ? parseInt(slotRaw, 10) : null,
    };
  }).filter((t) => t.id !== "");
}

/* ---------------- 转子 SVG ---------------- */

function slotPos(angleDeg, r, cx = 320, cy = 320) {
  const a = (angleDeg * Math.PI) / 180;
  return [cx + r * Math.sin(a), cy - r * Math.cos(a)];
}

function renderRotor(step) {
  const svg = $("rotorSvg");
  svg.innerHTML = "";
  const angles = getAngles();
  if (!angles) {
    el("text", { x: 320, y: 320, fill: "#ff6b6b", "text-anchor": "middle", "font-size": 16 }, svg)
      .textContent = "自定义角度数量与槽位数不一致";
    return;
  }
  const n = angles.length;
  const R = 270, RING = 226, LABEL_R = 266;
  const tubes = readTubes();
  const tubeById = new Map(tubes.map((t) => [t.id, t]));
  const placement = step ? step.placement : null;
  const slotToTube = new Map();
  if (placement) for (const [tid, si] of Object.entries(placement)) slotToTube.set(si, tid);

  // 箭头 marker
  const defs = el("defs", {}, svg);
  for (const [id, color] of [["ah1", "#ffb648"], ["ah2", "#4aa8ff"]]) {
    const mk = el("marker", {
      id, markerWidth: 10, markerHeight: 10, refX: 8, refY: 3,
      orient: "auto", markerUnits: "strokeWidth",
    }, defs);
    el("path", { d: "M0,0 L8,3 L0,6 Z", fill: color }, mk);
  }

  // 转子外圆 / 内环
  el("circle", { cx: 320, cy: 320, r: R, fill: "#131d29", stroke: "#2c3e52", "stroke-width": 3 }, svg);
  el("circle", { cx: 320, cy: 320, r: RING + 40, fill: "none", stroke: "#22303f", "stroke-width": 1, "stroke-dasharray": "3 5" }, svg);

  // 最终方案的配对连线
  if (state.result && (!step || step.phase === "final") && state.result.pairings) {
    state.result.pairings.forEach((p, i) => {
      if (p.type !== "pair") return;
      const [s1, s2] = p.slots;
      const [x1, y1] = slotPos(angles[s1], RING);
      const [x2, y2] = slotPos(angles[s2], RING);
      el("line", {
        x1, y1, x2, y2, stroke: "rgba(56,198,168,.25)",
        "stroke-width": 1.5, "stroke-dasharray": "5 5",
      }, svg);
    });
  }

  // 槽位
  angles.forEach((ang, si) => {
    const [x, y] = slotPos(ang, RING);
    const isDisabled = state.disabled.has(si);
    const tid = slotToTube.get(si);
    const t = tid ? tubeById.get(tid) : null;
    let fill = "#233040", stroke = "#3a4d62", strokeW = 1.5;
    if (isDisabled) { fill = "#2a323e"; stroke = "#445063"; }
    if (t) {
      fill = t.locked ? "#c084fc" : "#38c6a8";
      stroke = t.locked ? "#c084fc" : "#38c6a8";
    }
    const c = el("circle", {
      class: "slot-circle", cx: x, cy: y, r: 27,
      fill, stroke, "stroke-width": strokeW, "data-slot": si,
    }, svg);
    el("title", {}, c).textContent = `槽 ${si} · ${fmt(ang, 1)}°${
      isDisabled ? "（禁用）" : ""}${t ? ` · ${tid} ${fmt(t.mass, 1)}g${t.locked ? "（锁定）" : ""}` : ""}`;
    c.addEventListener("click", () => toggleDisabled(si));

    if (isDisabled) {
      el("line", { x1: x - 11, y1: y - 11, x2: x + 11, y2: y + 11, stroke: "#7d8da1", "stroke-width": 2.5 }, svg);
      el("line", { x1: x + 11, y1: y - 11, x2: x - 11, y2: y + 11, stroke: "#7d8da1", "stroke-width": 2.5 }, svg);
    }
    if (t) {
      const dark = !t.locked; // 绿色底用深字
      el("text", {
        x, y: y - 3, "text-anchor": "middle", class: "tube-label",
        fill: dark ? "#0b201b" : "#2a1240",
      }, svg).textContent = tid;
      el("text", {
        x, y: y + 11, "text-anchor": "middle",
        "font-size": 9, "font-weight": 600,
        fill: dark ? "rgba(11,32,27,.75)" : "rgba(42,18,64,.75)",
      }, svg).textContent = fmt(t.mass, 1) + "g";
      if (t.locked) {
        el("text", { x: x + 15, y: y - 15, "font-size": 11 }, svg).textContent = "🔒";
      }
    }

    // 槽号 / 角度标签
    const [lx, ly] = slotPos(ang, LABEL_R);
    el("text", {
      x: lx, y: ly + 3.5, "text-anchor": "middle",
      class: "slot-label", "font-size": n > 36 ? 8 : 10,
    }, svg).textContent = si;
  });

  // 中心轮毂
  el("circle", { cx: 320, cy: 320, r: 30, fill: "#1a2634", stroke: "#3a4d62", "stroke-width": 2 }, svg);
  el("circle", { cx: 320, cy: 320, r: 5, fill: "#5a718a" }, svg);

  // 合力箭头
  if (step && state.result) {
    const total = state.result.total_mass || 1;
    const drawArrow = (vx, vy, magGmm, color, markerId, dashed, label) => {
      if (magGmm < 1e-6) return;
      const magUnit = magGmm / state.result.rotor.radius_mm; // 等效克数
      const e = magUnit / total;
      const len = Math.max(6, Math.min(185, e * 700));
      const nx = vx / magUnit, ny = vy / magUnit;
      el("line", {
        x1: 320, y1: 320, x2: 320 + nx * len, y2: 320 + ny * len,
        stroke: color, "stroke-width": dashed ? 2.5 : 4,
        "stroke-linecap": "round",
        "marker-end": `url(#${markerId})`,
        "stroke-dasharray": dashed ? "7 5" : null,
        class: "force-arrow",
      }, svg);
      el("text", {
        x: 320 + nx * (len + 14), y: 320 + ny * (len + 14) + 4,
        "font-size": 11, fill: color, "text-anchor": "middle",
      }, svg).textContent = label;
    };
    drawArrow(step.vx, step.vy, step.u1, "#ffb648", "ah1", false,
      `U1 ${fmt(step.u1, 1)}`);
    drawArrow(step.v2x, step.v2y, step.u2, "#4aa8ff", "ah2", true,
      `U2 ${fmt(step.u2, 1)}`);
  }
}

function toggleDisabled(si) {
  // 若当前展示的是某个已计算方案的布局，该槽被占用时不直接禁用，
  // 避免图与结果不一致；先改配置再让用户重新计算。
  const step = currentStep();
  const occupied = step && step.placement &&
    Object.values(step.placement).includes(si);
  if (occupied) {
    alert(`槽 ${si} 在当前方案中放有试管。请先调整配置后重新计算配平方案。`);
    return;
  }
  if (state.disabled.has(si)) state.disabled.delete(si);
  else state.disabled.add(si);
  renderDisabledInfo();
  renderRotor(currentStep());
}

function renderDisabledInfo() {
  const box = $("disabledInfo");
  box.innerHTML = "";
  const arr = [...state.disabled].sort((a, b) => a - b);
  if (arr.length === 0) {
    box.innerHTML = '<span class="chip" style="color:var(--muted)">无禁用槽位</span>';
    return;
  }
  arr.forEach((si) => {
    const c = document.createElement("span");
    c.className = "chip";
    c.textContent = `槽 ${si} 已禁用 ✕`;
    c.style.cursor = "pointer";
    c.title = "点击恢复";
    c.addEventListener("click", () => toggleDisabled(si));
    box.appendChild(c);
  });
}

/* ---------------- 指标 ---------------- */

function clsByGrade(e1) {
  if (e1 < 0.03) return "good";
  if (e1 < 0.08) return "warn";
  return "bad";
}

function renderMetrics(res) {
  $("metricsWrap").classList.remove("hidden");
  const m = res.metrics;
  const cards = [
    ["一阶不平衡 |U1|", fmt(m.u1_gmm), "g·mm", clsByGrade(m.e1_norm),
      `方向 ${fmt(m.u1_angle_deg, 1)}°`],
    ["二阶不平衡 |U2|", fmt(m.u2_gmm), "g·mm",
      m.e2_norm < 0.05 ? "good" : m.e2_norm < 0.15 ? "warn" : "bad",
      `相位 ${fmt(m.u2_direction_deg, 1)}°（2倍频）`],
    ["归一化残差 e₁", fmt(m.e1_norm, 4), "|U1|/(M·r)", clsByGrade(m.e1_norm),
      `e₂ = ${fmt(m.e2_norm, 4)}`],
    ["配平等级", m.grade.split(" ")[0], m.grade.split(" ")[1] || "",
      clsByGrade(m.e1_norm), "按 |U1|/(M·r) 评定"],
    ["初始 → 优化 U1", `${fmt(m.init_u1_gmm)} → ${fmt(m.u1_gmm)}`,
      "g·mm", "good", `降低 ${fmt(m.improvement_pct, 1)}%`],
  ];
  if (m.centrifugal_force_n !== null) {
    cards.push(
      ["离心合力 F", fmt(m.centrifugal_force_n, 3), "N", clsByGrade(m.e1_norm),
        `@ ${fmt(res.rotor.rpm, 0)} rpm`],
      ["合力矩 F·r", fmt(m.resultant_moment_nmm, 2), "N·mm", clsByGrade(m.e1_norm),
        `半径 ${fmt(res.rotor.radius_mm, 0)} mm`],
    );
  }
  cards.push(["搜索统计",
    `${fmt(m.sa_iterations, 0)}`, "次迭代", "warn",
    `接受 ${m.sa_accepted} · 爬山 ${m.hill_moves} 步`]);

  $("metricCards").innerHTML = cards.map(([k, v, u, c, sub]) => `
    <div class="metric-card">
      <div class="k">${k}</div>
      <div class="v ${c}">${v} <span class="u">${u}</span></div>
      <div class="u">${sub}</div>
    </div>`).join("");

  const worse = m.e1_norm >= 0.08;
  $("gradeBanner").className = "grade-banner " + (worse ? "bad" : "");
  $("gradeBanner").innerHTML =
    `<strong style="color:${worse ? "var(--danger)" : "var(--accent)"}">${m.grade}</strong>：`
    + (worse
      ? "残余不平衡偏大。建议：增加对侧配平管、减小质量差、检查禁用槽位约束，或降低转速运行。"
      : "残余不平衡较小。注意等级仅按一阶合力评定，二阶分量反映结构交变载荷，请结合转速综合判断。");
}

/* ---------------- 配对解释 ---------------- */

function renderPairs(res) {
  $("pairsWrap").classList.remove("hidden");
  $("pairList").innerHTML = res.pairings.map((p) => {
    const head = p.type === "pair"
      ? `配对：${p.tubes.join(" ⟷ ")} <span class="pair-tag">对径对</span>`
      : `单管：${p.tubes[0]} <span class="pair-tag solo">无配对</span>`;
    return `<div class="pair-card">
      <div class="pair-head">${head}</div>
      <ul>${p.reasons.map((r) => `<li>${r}</li>`).join("")}</ul>
    </div>`;
  }).join("");
}

/* ---------------- 回放 ---------------- */

function currentStep() {
  if (!state.result) return null;
  return state.result.steps[state.stepIndex] || null;
}

const PHASE_ICON = { lock: "🔒", greedy: "🧱", "greedy-done": "🧱", optimize: "🔥", hillclimb: "🧗", final: "🏁" };

function renderStepList() {
  const ol = $("stepList");
  ol.innerHTML = state.result.steps.map((s, i) =>
    `<li data-i="${i}" class="${i === state.stepIndex ? "active" : ""}">
      ${PHASE_ICON[s.phase] || "•"} ${s.action}<span class="sp-u">U1 ${fmt(s.u1, 1)}</span>
    </li>`).join("");
  ol.querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", () => gotoStep(parseInt(li.dataset.i, 10)));
  });
}

function gotoStep(i) {
  const steps = state.result.steps;
  state.stepIndex = Math.max(0, Math.min(steps.length - 1, i));
  const s = steps[state.stepIndex];
  renderRotor(s);
  $("stepPos").textContent = `第 ${state.stepIndex + 1} / ${steps.length} 步`;
  $("stepMeta").innerHTML = `
    <div class="step-title">${PHASE_ICON[s.phase] || ""} ${s.action}</div>
    <div>${s.detail}</div>
    <div class="step-nums">|U1| = ${fmt(s.u1, 3)} g·mm ｜ |U2| = ${fmt(s.u2, 3)} g·mm ｜ J = ${fmt(s.score, 3)}</div>`;
  renderStepList();
  const active = $("stepList").querySelector("li.active");
  if (active) active.scrollIntoView({ block: "nearest" });
  // 走到最终步时同步指标配对视图已存在；非最终步淡化配对区
  $("pairsWrap").style.opacity = s.phase === "final" ? 1 : 0.45;
}

function setupReplay(res) {
  $("replayWrap").classList.remove("hidden");
  state.result = res;
  state.stepIndex = 0;
  stopPlay();
  renderStepList();
  gotoStep(res.steps.length - 1); // 默认展示最终方案
}

function stopPlay() {
  if (state.playing) { clearInterval(state.playing); state.playing = null; }
  $("stepPlay").textContent = "▶ 播放";
}

$("stepFirst")?.addEventListener("click", () => { stopPlay(); gotoStep(0); });
$("stepPrev")?.addEventListener("click", () => { stopPlay(); gotoStep(state.stepIndex - 1); });
$("stepNext")?.addEventListener("click", () => { stopPlay(); gotoStep(state.stepIndex + 1); });
$("stepLast")?.addEventListener("click", () => { stopPlay(); gotoStep(state.result.steps.length - 1); });
$("stepPlay")?.addEventListener("click", () => {
  if (state.playing) { stopPlay(); return; }
  if (state.stepIndex >= state.result.steps.length - 1) gotoStep(0);
  $("stepPlay").textContent = "⏸ 暂停";
  state.playing = setInterval(() => {
    if (state.stepIndex >= state.result.steps.length - 1) { stopPlay(); return; }
    gotoStep(state.stepIndex + 1);
  }, 750);
});

/* ---------------- 请求 / 结果 ---------------- */

function gatherRequest() {
  const n = parseInt($("nSlots").value, 10);
  const angles = getAngles();
  return {
    n_slots: n,
    angles,
    disabled: [...state.disabled],
    tubes: readTubes(),
    w1: parseFloat($("w1").value),
    w2: parseFloat($("w2").value),
    iterations: $("iterations").value ? parseInt($("iterations").value, 10) : null,
    rpm: $("rpm").value ? parseFloat($("rpm").value) : null,
    radius_mm: parseFloat($("radiusMm").value),
    seed: parseInt($("seed").value, 10) || 42,
  };
}

function showError(msg) {
  const box = $("errorBox");
  box.textContent = msg;
  box.classList.remove("hidden");
}
function clearError() { $("errorBox").classList.add("hidden"); }

async function runBalance(persist) {
  clearError();
  const angles = getAngles();
  if (!angles) { showError("自定义角度的数量必须等于槽位数，且全部为数字。"); return; }
  const req = gatherRequest();
  const tubes = req.tubes;
  if (tubes.length === 0) { showError("请至少添加一支试管。"); return; }
  const ids = tubes.map((t) => t.id);
  if (new Set(ids).size !== ids.length) { showError("试管编号存在重复。"); return; }
  if (tubes.some((t) => !(t.mass > 0))) { showError("所有试管质量必须为正数。"); return; }

  $("runBtn").disabled = true;
  try {
    const resp = await fetch(persist ? "/api/plans" : "/api/balance", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    const data = await resp.json();
    if (!resp.ok) {
      showError(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
      return;
    }
    const result = persist ? data.result : data;
    state.requestSnapshot = req;
    state.savedId = persist ? data.id : null;
    applyResult(result);
    $("saveBtn").disabled = persist;
    $("exportBtn").disabled = false;
    if (persist) loadPlans();
  } catch (e) {
    showError("请求失败：" + e.message);
  } finally {
    $("runBtn").disabled = false;
  }
}

function applyResult(result) {
  renderMetrics(result);
  renderPairs(result);
  setupReplay(result);
}

function downloadJson(obj, filename) {
  const blob = new Blob([JSON.stringify(obj, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------------- 历史方案 ---------------- */

async function loadPlans() {
  const resp = await fetch("/api/plans");
  const data = await resp.json();
  const tbody = $("plansTable").querySelector("tbody");
  if (!data.plans.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--muted)">暂无保存的方案</td></tr>';
    return;
  }
  tbody.innerHTML = data.plans.map((p) => `
    <tr data-id="${p.id}">
      <td>${p.id}</td>
      <td>${p.name}</td>
      <td>${p.n_slots} 槽</td>
      <td>${fmt(p.u1_gmm)}</td>
      <td>${p.grade}</td>
      <td>
        <button class="btn btn-sm act-load">回放</button>
        <a class="btn btn-sm" href="/api/plans/${p.id}/export" download>导出</a>
        <button class="btn btn-sm btn-danger act-del">删除</button>
      </td>
    </tr>`).join("");
  tbody.querySelectorAll(".act-load").forEach((b) =>
    b.addEventListener("click", () => loadPlan(b.closest("tr").dataset.id)));
  tbody.querySelectorAll(".act-del").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("确定删除该方案？")) return;
      const id = b.closest("tr").dataset.id;
      await fetch("/api/plans/" + id, { method: "DELETE" });
      loadPlans();
    }));
}

async function loadPlan(id) {
  const resp = await fetch("/api/plans/" + id);
  if (!resp.ok) return;
  const plan = await resp.json();
  const r = plan.request;
  $("nSlots").value = r.n_slots;
  $("radiusMm").value = r.radius_mm;
  $("rpm").value = r.rpm ?? "";
  $("w1").value = r.w1; $("w2").value = r.w2;
  $("seed").value = r.seed;
  $("iterations").value = r.iterations ?? "";
  if (r.angles && r.angles.some((a, i) => Math.abs(a - 360 * i / r.n_slots) > 1e-6)) {
    $("angleMode").value = "custom";
    $("customAngles").value = r.angles.map((a) => fmt(a, 2)).join(",");
  } else {
    $("angleMode").value = "uniform";
    $("customAngles").value = "";
  }
  $("customAnglesWrap").classList.toggle("hidden", $("angleMode").value !== "custom");
  state.disabled = new Set(r.disabled);
  renderDisabledInfo();
  $("tubesTable").querySelector("tbody").innerHTML = "";
  tubeSeq = 0;
  r.tubes.forEach((t) => addTubeRow(t.id, t.mass, t.locked, t.locked_slot));
  state.requestSnapshot = r;
  state.savedId = plan.id;
  applyResult(plan.result);
  $("saveBtn").disabled = true;
  $("exportBtn").disabled = false;
}

/* ---------------- 示例 ---------------- */

function loadSample() {
  $("nSlots").value = 12;
  $("angleMode").value = "uniform";
  $("customAnglesWrap").classList.add("hidden");
  $("radiusMm").value = 100;
  $("rpm").value = 5000;
  state.disabled = new Set([11]);
  $("tubesTable").querySelector("tbody").innerHTML = "";
  tubeSeq = 0;
  addTubeRow("L1", 12.0, true, 0);
  addTubeRow("X", 11.5, false);
  addTubeRow("Y", 8.0, false);
  addTubeRow("Z", 8.2, false);
  addTubeRow("W", 4.0, false);
  renderDisabledInfo();
  renderRotor(null);
}

/* ---------------- 事件绑定 ---------------- */

$("addTube").addEventListener("click", () => addTubeRow());
$("loadSample").addEventListener("click", loadSample);
$("runBtn").addEventListener("click", () => runBalance(false));
$("saveBtn").addEventListener("click", () => runBalance(true));
$("exportBtn").addEventListener("click", () => {
  if (!state.result) return;
  if (state.savedId) { window.location.href = `/api/plans/${state.savedId}/export`; return; }
  downloadJson({
    exported_at: new Date().toISOString(),
    request: state.requestSnapshot,
    result: state.result,
  }, "balance_plan.json");
});

function refreshConfig() {
  state.disabled = new Set([...state.disabled].filter((i) => i < parseInt($("nSlots").value, 10)));
  renderDisabledInfo();
  renderRotor(currentStep());
}
$("nSlots").addEventListener("change", refreshConfig);
$("radiusMm").addEventListener("change", () => renderRotor(currentStep()));
$("angleMode").addEventListener("change", () => {
  $("customAnglesWrap").classList.toggle("hidden", $("angleMode").value !== "custom");
  renderRotor(currentStep());
});
$("customAngles").addEventListener("input", () => renderRotor(currentStep()));
$("tubesTable").addEventListener("input", () => renderRotor(currentStep()));
$("tubesTable").addEventListener("change", () => renderRotor(currentStep()));

/* ---------------- 初始化 ---------------- */

renderDisabledInfo();
loadSample();
loadPlans();
