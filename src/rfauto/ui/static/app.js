/* rfauto 射频调优工作台前端（vanilla JS + three.js，无构建步骤）。
   本文件 = 外壳（导航/工具函数/3D）；各页面逻辑在 pages.js。 */
import * as THREE from "three";
import { initPages, showPage, esc } from "./pages.js";
// PR-3 PlotCard：option 构造单源在 plotcard.js（buildEChartOption 与
// 迁移前 drawEChart 逐字节等价，golden 快照钉 runs/pr34），drawEChart
// 与 plotCard 共用；drawLineChart/Smith/3D 自研管线不动。
import { buildEChartOption, plotCard } from "./plotcard.js";

const $ = (id) => document.getElementById(id);
export const api = async (url, opts) => {
  const r = await fetch(url, opts);
  return r.json();
};
export const $id = $;
export function msg(text, ok) {
  const el = $("msg");
  el.textContent = text;
  el.className = "msg " + (ok ? "ok" : "err");
  if (ok) setTimeout(() => (el.className = "msg"), 4000);
}

/* ── 导航 ── */
const navBtns = [...document.querySelectorAll("#nav button")];
for (const b of navBtns) {
  b.onclick = () => showPage(b.dataset.v);
}
function activate(v) {
  for (const b of navBtns) {
    b.classList.toggle("active", b.dataset.v === v);
    // PR-1 a11y：当前页 aria-current（读屏可知导航位置）
    if (b.dataset.v === v) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
    if (b.dataset.v === "detail")
      b.style.display = v === "detail" ? "" : "none"; // 详情页仅从 run 点入时显示
  }
  for (const s of document.querySelectorAll("main > section"))
    s.style.display = s.id === "view-" + v ? "" : "none";
}

/* 通用小部件：徽章（text 一律 esc 转义后再插值——AU-4：badge 是 API 数据
   的 HTML 出口之一（如 run status/anchor 状态），单点转义覆盖全部调用面） */
export const badge = (text, cls) => `<span class="badge ${cls}">${esc(text)}</span>`;
export const passBadge = (p) =>
  p === true ? badge("PASS", "ok") : p === false ? badge("FAIL", "err") : badge("N/A", "muted");

/* PR-1 对比度：图表系列调色板按主题分档（核算见 runs/pr1_contrast）。
   深色档对 --plot-bg #0d1118、浅色档对白底逐色 ≥3:1（WCAG 图形）。
   显式 s.color 仍优先——调色板只兜底缺省系列。 */
const CHART_COLORS = {
  dark: ["#4fc3f7", "#ffb74d", "#81c784", "#e57373", "#ba68c8"],
  light: ["#0277bd", "#b26a00", "#276b2c", "#c62828", "#6a1b9a"],
};

/* 通用折线图（canvas，多曲线 + 主题自适应网格） */
export function drawLineChart(canvas, series, labels) {
  const ctx = canvas.getContext("2d");
  canvas.width = canvas.clientWidth || 600;
  canvas.height = canvas.clientHeight || 260;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const light = document.body.classList.contains("light");
  const gridColor = light ? "#dde3ec" : "#1c2331"; // 网格线=装饰性（读数靠刻度文字）
  const readColor = light ? "#5f6a80" : "#7d8aa0"; // 刻度文字：双主题对底 ≥4.5:1
  if (!series.length || !series[0].x.length) return;
  // PR-1 a11y：canvas 图像语义
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label",
    `折线图：${series.map((s) => s.name).filter(Boolean).join("、") || "数据系列"}`);
  const W = canvas.width, H = canvas.height, L = 46, R = 14, T = 14, B = 26;
  const xs = series.flatMap((s) => s.x), ys = series.flatMap((s) => s.y);
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const ymin = Math.min(...ys), ymax = Math.max(...ys);
  const px = (x) => L + ((x - xmin) / (xmax - xmin || 1)) * (W - L - R);
  const py = (y) => H - B - ((y - ymin) / (ymax - ymin || 1)) * (H - T - B);
  ctx.strokeStyle = gridColor;
  ctx.beginPath();
  for (let i = 0; i <= 4; i++) {
    const gx = L + (i / 4) * (W - L - R), gy = T + (i / 4) * (H - T - B);
    ctx.moveTo(gx, T); ctx.lineTo(gx, H - B);
    ctx.moveTo(L, gy); ctx.lineTo(W - R, gy);
  }
  ctx.stroke();
  const colors = CHART_COLORS[light ? "light" : "dark"];
  series.forEach((s, i) => {
    ctx.strokeStyle = s.color || colors[i % colors.length];
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    s.x.forEach((x, j) => (j ? ctx.lineTo(px(x), py(s.y[j])) : ctx.moveTo(px(x), py(s.y[j]))));
    ctx.stroke();
  });
  ctx.fillStyle = readColor;
  ctx.font = "11px sans-serif";
  ctx.fillText(xmin.toFixed(2), L, H - 8);
  ctx.fillText(xmax.toFixed(2), W - R - 40, H - 8);
  ctx.fillText(ymax.toFixed(1), 4, T + 8);
  ctx.fillText(ymin.toFixed(1), 4, H - B);
  if (labels) {
    ctx.textAlign = "right";
    series.forEach((s, i) => {
      ctx.fillStyle = s.color || colors[i % colors.length];
      ctx.fillText(s.name || labels[i] || "", W - R, T + 10 + i * 14);
    });
  }
}

/* 交互式图表（ECharts：缩放/悬停读数/图例开关），theme 自适应。
   PR-3：option 构造委托 plotcard.js 单源 builder（等价快照钉在
   tests/unit/test_ui_plotcard.py）；本壳保留容器语义（role/aria/height）
   与故障可见化。新调用面请用 plotCard（带导出/十字线/收敛模式）。 */
export function drawEChart(el, series, opts = {}) {
  try {
    const light = document.body.classList.contains("light");
    // PR-1 a11y：图表容器图像语义（系列名+轴标签进 aria-label；opts.ariaLabel 显式覆盖）
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", opts.ariaLabel ||
      `图表：${series.map((s) => s.name).filter(Boolean).join("、") || "数据系列"}` +
      `${opts.ylabel ? "，纵轴 " + opts.ylabel : ""}${opts.xlabel ? "，横轴 " + opts.xlabel : ""}`);
    el.innerHTML = "";
    el.style.height = opts.height || "280px";
    const chart = window.echarts.init(el);
    chart.setOption(buildEChartOption(series, opts, {
      light,
      palette: CHART_COLORS[light ? "light" : "dark"],
    }));
    window.addEventListener("resize", () => chart.resize());
    return chart;
  } catch (e) {
    // 图表故障可见化——不静默吞错（排查 #135 教训）
    el.innerHTML = `<span style="color:var(--err)">chart error: ${esc(e.message)}</span>`;
    return null;
  }
}

/* PR-3 PlotCard 注入：主题态在本壳现取（与 drawEChart 同一判定时机），
   调色板单源 CHART_COLORS 传入 plotcard.js。 */
function uiPlotCard(el, props = {}) {
  const light = document.body.classList.contains("light");
  return plotCard(el, props, {
    light,
    palette: CHART_COLORS[light ? "light" : "dark"],
  });
}

/* ── 灯箱 ── */
export function lightboxContent(node, cap) {
  $("lightbox-cap").textContent = cap || "";
  const lb = $("lightbox");
  lb.querySelectorAll("canvas,img").forEach((el) => el.remove());
  lb.insertBefore(node, lb.firstChild);
  lb.classList.add("show");
}
export function lightboxImg(src, cap) {
  const img = document.createElement("img");
  img.src = src;
  lightboxContent(img, cap);
}
$("lightbox").onclick = () => $("lightbox").classList.remove("show");

/* ── 3D 渲染（three.js，沿用电位配色） ── */
const MATERIAL_COLORS = { metal: 0xc0c8d0, substrate: 0x2e7d32 };
const BOX_COLORS = { ground: 0x556070 };

function makeLabelSprite(text, color) {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 96;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "rgba(17,20,26,0.8)";
  ctx.roundRect?.(0, 0, c.width, c.height, 12);
  ctx.fill();
  ctx.font = "bold 40px sans-serif";
  ctx.fillStyle = color || "#dce3ee";
  ctx.textAlign = "center";
  ctx.fillText(text, c.width / 2, 62);
  const tex = new THREE.CanvasTexture(c);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  sp.scale.set(20, 3.75, 1);
  return sp;
}

export function drawBoxes(container, spec) {
  container.innerHTML = "";
  if (!spec || !spec.ok) {
    container.innerHTML = `<span class="muted">${spec ? esc(spec.errors.join("; ")) : "无几何"}</span>`;
    return;
  }
  const w = container.clientWidth || 600, h = 420;
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d1118);
  const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 2000);
  const c = [0, 0, 0];
  for (const b of spec.boxes) for (let i = 0; i < 3; i++) c[i] += (b.start_mm[i] + b.stop_mm[i]) / 2 / spec.boxes.length;
  const group = new THREE.Group();
  for (const b of spec.boxes) {
    const size = b.stop_mm.map((v, i) => Math.max(Math.abs(v - b.start_mm[i]), 0.05));
    const color = BOX_COLORS[b.name] || MATERIAL_COLORS[b.material] || 0x999999;
    const mat = new THREE.MeshPhongMaterial({
      color, transparent: b.material === "substrate", opacity: b.material === "substrate" ? 0.45 : 0.9,
    });
    // 轴向映射与下方 position 一致：模型 (x,y,z) → 场景 (x, z, y)，
    // 模型 z=高度（基板厚度轴）映射为场景竖直方向（three.js y=上）。
    // 尺寸必须与位置做同一轴交换（2026-09-15 修复：基板 120×120×0.51
    // 曾被 BoxGeometry(size[1]=120) 当高度渲染成竖立大板）。
    const geo = new THREE.BoxGeometry(size[0], size[2], size[1]);
    const mesh = new THREE.Mesh(geo, mat);
    const mid = b.start_mm.map((v, i) => (v + b.stop_mm[i]) / 2);
    mesh.position.set(mid[0] - c[0], mid[2] - c[2], mid[1] - c[1]);
    mesh.add(new THREE.LineSegments(
      new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: 0x0a0c10 })));
    group.add(mesh);
  }
  const portNotes = [];
  for (const p of spec.ports || []) {
    // dir 是模型坐标向量，与盒体做同一 (x,y,z)→(x,z,y) 轴交换
    const dir = new THREE.Vector3(p.dir[0], p.dir[2], p.dir[1]);
    const pos = new THREE.Vector3(p.pos_mm[0] - c[0], p.pos_mm[2] - c[2], p.pos_mm[1] - c[1]);
    const cone = new THREE.Mesh(
      new THREE.ConeGeometry(1.6, 6, 16),
      new THREE.MeshPhongMaterial({ color: 0xffb74d }));
    cone.position.copy(pos).addScaledVector(dir, 3);
    cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
    group.add(cone);
    const label = makeLabelSprite(p.name, "#ffb74d");
    label.position.copy(pos).addScaledVector(dir, 9);
    label.position.z += 4;
    group.add(label);
    portNotes.push(p.name);
  }
  scene.add(group);
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dl = new THREE.DirectionalLight(0xffffff, 0.9);
  dl.position.set(80, 120, 60);
  scene.add(dl);
  scene.add(new THREE.GridHelper(240, 24, 0x242c3d, 0x242c3d));
  // 相机自动取景：按模型包围盒最大维度缩放
  const bbox = new THREE.Box3().setFromObject(group);
  const maxDim = Math.max(
    bbox.max.x - bbox.min.x, bbox.max.y - bbox.min.y, bbox.max.z - bbox.min.z, 10);
  camera.position.set(60, 70, 90);
  camera.lookAt(0, 0, 0);
  orbitLike(camera, renderer.domElement, maxDim);
  renderer.setAnimationLoop(() => renderer.render(scene, camera));
  const legend = document.createElement("div");
  legend.className = "legend3d";
  const chip = (color, name) =>
    `<span class="muted"><span class="chip" style="background:#${color.toString(16).padStart(6, "0")}"></span>${name}</span>`;
  const deviceList = spec.boxes
    .map((b) => {
      const d = b.stop_mm.map((v, i) => Math.abs(v - b.start_mm[i]));
      return `${b.name}（${d.map((v) => +v.toFixed(2)).join("×")} mm）`;
    })
    .join("、");
  legend.innerHTML =
    chip(0xc0c8d0, "金属") + chip(0x556070, "地面") + chip(0x2e7d32, "基板") +
    chip(0xffb74d, "端口") +
    (portNotes.length ? `<span class="muted">　端口: ${esc(portNotes.join("、"))}</span>` : "") +
    `<div class="muted" style="margin-top:4px">器件: ${esc(deviceList)}</div>` +
    `<div class="muted">拖动旋转 / 滚轮缩放</div>`;
  container.appendChild(legend);
  // PR-1 a11y：3D 视图图像语义（器件清单可闻；交互提示留在图例文字里）
  container.setAttribute("role", "img");
  container.setAttribute("aria-label",
    `3D 模型预览：${deviceList}${portNotes.length ? "，端口 " + portNotes.join("、") : ""}`);
}

function orbitLike(camera, dom, maxDim = 120) {
  let dragging = false, px = 0, py = 0, theta = 0.7, phi = 1.05, radius = maxDim * 1.9;
  const apply = () => {
    camera.position.set(
      radius * Math.sin(phi) * Math.cos(theta),
      radius * Math.cos(phi),
      radius * Math.sin(phi) * Math.sin(theta));
    camera.lookAt(0, 0, 0);
  };
  apply();
  dom.onpointerdown = (e) => { dragging = true; px = e.clientX; py = e.clientY; };
  dom.onpointerup = () => (dragging = false);
  dom.onpointermove = (e) => {
    if (!dragging) return;
    theta += (e.clientX - px) * 0.008; phi -= (e.clientY - py) * 0.008;
    phi = Math.max(0.1, Math.min(3.0, phi));
    px = e.clientX; py = e.clientY; apply();
  };
  dom.onwheel = (e) => { e.preventDefault(); radius *= e.deltaY > 0 ? 1.1 : 0.9; apply(); };
}

initPages({
  activate, msg, api, badge, passBadge, drawLineChart, drawEChart, drawBoxes,
  lightboxImg, lightboxContent, $, THREE, plotCard: uiPlotCard,
});
showPage("dashboard");
