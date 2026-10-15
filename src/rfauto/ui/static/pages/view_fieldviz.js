/* rfauto 场/远场可视化页族（aurora_d UI-R2 自 pages.js 拆出，逐字节
   搬移）：远场极坐标（nf2ff）+ Smith 圆图（G9，S 参数页复用）+ 场切片
   热图/等值面/远场 3D（DumpHDF5）。自研管线（polar/Smith/custom/
   heatmap 不在 plotcard builder 能力面），仅补 plotCard 级导出面。 */

import { HEAT_BAND, ISO_BAND, THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import {
  _isoRenderers,
  bindChartResize,
  chartExportTools,
  disposeChartsIn,
  echartsInitCached,
  releaseWebGLIn,
  smithChartTheme, // UI-R5：Smith 网格/轨迹色对走 charts 层选项工厂
} from "./charts.js";
import { S, T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { showPage } from "./router.js";

/* ── 远场极坐标页（WP4.1/D4：nf2ff 方向图 + 增益/效率/SAR）───────────── */
export async function pageFarfield() {
  const v = T.$("view-farfield");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>数据源 = openEMS 真跑 run 的 nf2ff 产物（模板 far_field/sar=True 渲染：farfield_cut/3d.csv + farfield_meta.json + sar.csv）。</li>
      <li>极坐标切面：φ=0°（xz 面）与 φ=90°（yz 面），θ −180..180°，dB 相对峰值归一。</li>
      <li>指标口径（官方 nf2ff 教程）：Dmax=方向性（dBi），η=Prad/P_acc（辐射效率），G=η·D；HPBW=半功率波瓣宽度；功率闭合=|P_acc−Prad|/P_acc（SAR 注入时 P_acc−Prad=组织吸收）。</li>
      <li>SAR（官方 Dipole SAR 教程）：IEEE_62704 1g 平均，含 1W 接受功率归一值。</li>`) +
    `<h2 class='page'>远场方向图<small>nf2ff · 方向图/增益/效率 · SAR</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='ff-run' style='max-width:340px'></select>
         <span id='ff-info' class='muted'></span></div>
       <div id='ff-metrics' class='toolbar' style='flex-wrap:wrap;gap:14px'></div>
       <div id='ff-polar'></div>
       <div id='ff-sar'></div>
     </div>`;
  const runs = (await T.api("/api/farfield")).runs || [];
  const sel = T.$("ff-run");
  if (!runs.length) {
    sel.innerHTML = "<option>（无远场产物 run）</option>";
    T.$("ff-info").textContent =
      "先用 openEMS 通道以 far_field=True 渲染并真跑 patch/dipole 模板";
    return;
  }
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}${r.has_sar ? " ·SAR" : ""}</option>`).join("");
  if (S.ffRunId) sel.value = S.ffRunId;

  async function load() {
    S.ffRunId = sel.value;
    const d = await T.api("/api/farfield/" + encodeURIComponent(sel.value));
    if (!d.ok) { T.$("ff-info").textContent = (d.errors || []).join("; "); return; }
    T.$("ff-info").textContent = `模板 ${d.template || "?"} · f_res=${(d.metrics.f_res_ghz ?? 0).toFixed(3)} GHz`;
    const m = d.metrics || {};
    const fmt = (x, unit, digits = 2) => (x === null || x === undefined || Number.isNaN(+x))
      ? "N/A" : `${(+x).toFixed(digits)}${unit}`;
    T.$("ff-metrics").innerHTML = [
      `方向性 <b>${fmt(m.dmax_dbi, " dBi")}</b>`,
      `峰值增益 <b>${fmt(m.gain_max_dbi, " dBi")}</b>`,
      `辐射效率 <b>${fmt(m.efficiency !== null && m.efficiency !== undefined ? m.efficiency * 100 : null, "%", 1)}</b>`,
      `功率闭合 <b>${fmt(m.power_budget_closure === null || m.power_budget_closure === undefined ? null : m.power_budget_closure * 100, "%", 2)}</b>`,
    ].concat(m.eta_gate ? [
      // patch 族 η 门（服务层 farfield_view 复用 patch_eta_gate 判读，此处只渲染，与场页同口径）
      `η 门 <b style='color:var(${m.eta_gate.ok === null ? "--muted" : m.eta_gate.ok ? "--ok" : "--err"})'>${m.eta_gate.ok === null ? "N/A" : m.eta_gate.ok ? "PASS" : "FAIL"}</b> [${esc(m.eta_gate.gate.join(", "))}]`,
    ] : []).concat((m.sar && m.sar.ok !== false) ? [
      `SAR(1g) <b>${fmt(m.sar.sar_max_w_per_kg_per_1w_acc, " W/kg/W", 3)}</b> @1W接受`,
      `吸收占比 <b>${fmt(m.sar.absorbed_fraction === null || m.sar.absorbed_fraction === undefined ? null : m.sar.absorbed_fraction * 100, "%", 1)}</b>`,
    ] : []).map((s) => `<span>${s}</span>`).join("");
    // 极坐标切面（echarts polar：angleAxis=θ，radiusAxis=dB）
    const box = T.$("ff-polar");
    disposeChartsIn(box); // P0-5：子树重建前释放旧切面图实例（缓存键随元素走）
    box.innerHTML = (d.cuts || []).map((c, i) =>
      `<div style='margin-bottom:var(--space-2)'><b class='muted'>φ=${c.phi_deg}° 切面` +
      `（HPBW ${c.hpbw_deg === null ? "N/A" : c.hpbw_deg.toFixed(1) + "°"} · ` +
      `F/B ${c.front_to_back_db === null ? "N/A" : c.front_to_back_db.toFixed(1) + " dB"}）</b>` +
      `<div id='ff-pol-${i}'></div></div>`).join("");
    (d.cuts || []).forEach((c, i) => {
      try {
        const light = bodyIsLight();
        const fg = themePick(light, THEME_COLORS.fg);
        const axisLine = themePick(light, THEME_COLORS.fieldAxisLine); // UI-R12 任务3：单源收编
        const el = T.$(`ff-pol-${i}`);
        el.style.height = "360px";
        const chart = echartsInitCached(el); // P0-5：实例缓存守卫（存活即复用）
        chart.setOption({
          backgroundColor: "transparent",
          tooltip: {},
          angleAxis: {
            type: "value", min: -180, max: 180, startAngle: 90,
            axisLine: { lineStyle: { color: axisLine } }, // UI-R12：THEME_COLORS 单源（原内联 #55607a 冻结迁移）
            axisLabel: { color: fg }, splitLine: { show: true },
          },
          radiusAxis: {
            min: -40, max: 0,
            axisLine: { lineStyle: { color: axisLine } }, // UI-R12：同上
            axisLabel: { color: fg }, splitLine: { show: true },
          },
          polar: {},
          series: [{
            type: "line", coordinateSystem: "polar", showSymbol: false,
            data: c.theta_deg.map((t, j) => [c.pattern_db[j], t]),
            lineStyle: { width: 1.8,
              color: themePick(bodyIsLight(), THEME_COLORS.seriesBlue) },
          }],
        }, true); // notMerge：复用路径整体替换旧 option
        bindChartResize(el); // P0-5：resize 去重（WeakSet 标记，一容器一监听）
        // W3-B：plotCard 级导出面——polar 坐标系不在 plotcard builder 能力面
        //（仅笛卡尔 line/scatter/band），渲染管线保留自研，仅补导出（共用工厂）
        chartExportTools(el.parentElement, el, {
          name: "farfield-polar-phi" + c.phi_deg,
          getChart: () => chart,
          getCsvSeries: () => [{ name: `φ=${c.phi_deg}° pattern_db（x=θ°）`,
                                 x: c.theta_deg, y: c.pattern_db }],
        });
      } catch (e) {
        T.$(`ff-pol-${i}`).innerHTML = `<span style="color:var(--err)">polar error: ${esc(e.message)}</span>`;
      }
    });
    // SAR 块（有产物才渲染）
    T.$("ff-sar").innerHTML = (m.sar && m.sar.ok !== false)
      ? `<div class='muted' style='margin-top:6px'>SAR：IEEE_62704 1g 平均` +
        `（f_res=${(m.f_res_ghz ?? 0).toFixed(3)} GHz · ` +
        `原始值 ${fmt(m.sar.sar_max_w_per_kg, " W/kg", 3)}；归一值按 1W 端口接受功率折算）</div>`
      : "";
  }
  sel.onchange = load;
  await load();
}

/* ── Smith 圆图（G9，S 参数页增强）：网格几何+轨迹全部来自服务层 JSON ── */
export function drawSmith(el, traces, grid, z0) {
  try {
    const light = bodyIsLight();
    const fg = themePick(light, THEME_COLORS.fg);
    // UI-R5：网格/轨迹色对走 charts 层 smithChartTheme 工厂（色值单源仍在
    // theme.js smithPalette/smithGrid——工厂只做一对一次取齐）
    const { grid: gridColor, palette: colors } = smithChartTheme(light);
    const size = Math.min(el.clientWidth || 560, 560);
    const chart = echartsInitCached(el); // P0-5：实例缓存守卫（清容器移入新建路径）
    el.style.height = `${size}px`;
    el.style.width = `${size}px`;
    const gline = (pts, dashed) => ({
      type: "line", data: pts, showSymbol: false, silent: true, animation: false,
      lineStyle: { color: gridColor, width: dashed ? 0.8 : 1, type: dashed ? "dashed" : "solid" },
      tooltip: { show: false },
    });
    const series = [];
    if (grid) {
      series.push(gline(grid.unit_circle, false));
      for (const c of grid.r_circles) series.push(gline(c.points, false));
      for (const a of grid.x_arcs) series.push(gline(a.points, true));
      series.push(gline([[-1, 0], [1, 0]], false));
    }
    // 轨迹色=smithChartTheme.palette（theme.js smithPalette 单源经工厂取齐）
    traces.forEach((t, i) => series.push({
      name: t.label || t.name, type: "line", showSymbol: true, symbolSize: 3,
      data: t.re.map((re, k) => [re, t.im[k]]),
      lineStyle: { width: 1.6, color: colors[i % colors.length] },
      itemStyle: { color: colors[i % colors.length] },
      _trace: t,
    }));
    chart.setOption({
      backgroundColor: "transparent",
      legend: { top: 0, textStyle: { color: fg }, type: "scroll",
                data: traces.map((t) => t.label || t.name) },
      grid: { left: 10, right: 10, top: 28, bottom: 10, containLabel: false },
      xAxis: { type: "value", min: -1.12, max: 1.12, show: false },
      yAxis: { type: "value", min: -1.12, max: 1.12, show: false },
      tooltip: {
        trigger: "item",
        formatter: (p) => {
          // 轨迹系列排在网格系列之后：seriesIndex − 网格系列数 = 轨迹下标
          const t = traces[p.seriesIndex - (series.length - traces.length)];
          if (!t) return "";
          const k = p.dataIndex;
          const z = t.z_re_ohm[k] === null ? "N/A（|Γ|→1）"
            : `${t.z_re_ohm[k].toFixed(2)} ${t.z_im_ohm[k] >= 0 ? "+" : "−"} j${Math.abs(t.z_im_ohm[k]).toFixed(2)} Ω`;
          return `${p.seriesName}<br>f = ${t.freq_ghz[k]} GHz<br>Γ = ${t.re[k].toFixed(4)} ${t.im[k] >= 0 ? "+" : "−"} j${Math.abs(t.im[k]).toFixed(4)}（|Γ| ${t.mag[k].toFixed(4)}）<br>Z = ${z}`;
        },
      },
      series,
    }, true); // notMerge：复用路径整体替换旧 option
    // PR-1 a11y：图表容器图像语义（轨迹名 + Z0 进 aria-label，读屏可闻）
    el.setAttribute("role", "img");
    el.setAttribute("aria-label",
      `Smith 圆图：${(traces.map((t) => t.label || t.name)).join("、") || "无轨迹"}（Z0=${z0 ?? 50}Ω）`);
    const note = document.createElement("div");
    note.className = "muted";
    note.style.marginTop = "4px";
    note.textContent = `Z0 = ${z0 ?? 50} Ω · 网格 r=${(grid ? grid.r_circles.map((c) => c.r) : []).join("/")}、±x 同档 · 轨迹点 = 各频点 Γ（起点=首频）`;
    el.parentElement.appendChild(note);
    bindChartResize(el); // P0-5：resize 去重（WeakSet 标记）
    // W3-B：plotCard 级导出面——Smith 隐藏轴等比坐标 + 网格几何系列不在
    // plotcard builder 能力面，渲染管线保留自研，仅补导出（共用工厂）；
    // CSV=每轨迹 Γ 实/虚部两条长表系列（x=freq_ghz）
    chartExportTools(el.parentElement, el, {
      name: "smith-chart",
      getChart: () => chart,
      getCsvSeries: () => traces.flatMap((t) => {
        const nm = t.label || t.name;
        return [
          { name: nm + " Re(Γ)", x: t.freq_ghz, y: t.re },
          { name: nm + " Im(Γ)", x: t.freq_ghz, y: t.im },
        ];
      }),
    });
    return chart;
  } catch (e) {
    el.innerHTML = `<span style="color:var(--err)">smith error: ${esc(e.message)}</span>`;
    return null;
  }
}

/* ── 场可视化 3D 页（G9：openEMS DumpHDF5 切片热图/等值线 + PyVista 等值面 + 远场 3D）── */

/* 非均匀网格切片热图：自定义系列按真实 mm 单元格绘制矩形（openEMS 网格非均匀，
   category 热图会拉伸格子），等值线以 mm 坐标叠加在同一值轴上。 */
function drawFieldSlice(el, slice, contours, vmin) {
  try {
    const light = bodyIsLight();
    const fg = themePick(light, THEME_COLORS.fg);
    const u = slice.u_mm, v = slice.v_mm, vals = slice.values;
    const edges = (a) => {
      if (a.length === 1) return [a[0] - 0.5, a[0] + 0.5];
      const e = [a[0] - (a[1] - a[0]) / 2];
      for (let i = 0; i < a.length - 1; i++) e.push((a[i] + a[i + 1]) / 2);
      e.push(a[a.length - 1] + (a[a.length - 1] - a[a.length - 2]) / 2);
      return e;
    };
    const ue = edges(u), ve = edges(v);
    const cells = [];
    for (let j = 0; j < v.length; j++)
      for (let i = 0; i < u.length; i++) cells.push([ue[i], ve[j], ue[i + 1], ve[j + 1], vals[j][i]]);
    const chart = echartsInitCached(el); // P0-5：实例缓存守卫（清容器移入新建路径）
    el.style.height = "300px";
    const series = [{
      type: "custom", name: "|E| dB", data: cells, animation: false,
      renderItem: (params, api) => {
        const p0 = api.coord([api.value(0), api.value(1)]);
        const p1 = api.coord([api.value(2), api.value(3)]);
        return { type: "rect",
          shape: { x: Math.min(p0[0], p1[0]), y: Math.min(p0[1], p1[1]),
                   width: Math.abs(p1[0] - p0[0]) + 0.5, height: Math.abs(p1[1] - p0[1]) + 0.5 },
          style: { fill: api.visual("color") } };
      },
      encode: { x: [0, 2], y: [1, 3], tooltip: 4 },
    }];
    const levelColors = ISO_BAND; // UI-R12 任务3：等值线分档色单源（theme.js，冻结现值）
    for (const seg of contours || []) {
      const li = (seg._levelIndex ?? 0) % levelColors.length;
      series.push({ type: "line", data: seg.points, showSymbol: false, silent: true, animation: false,
                    name: `iso ${seg.level_db ?? ""} dB`,
                    lineStyle: { width: 1.2, color: levelColors[li] }, tooltip: { show: false } });
    }
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "item", formatter: (p) => p.seriesType === "custom"
        ? `${slice.u_axis}∈[${p.value[0].toFixed(2)},${p.value[2].toFixed(2)}] mm · ${slice.v_axis}∈[${p.value[1].toFixed(2)},${p.value[3].toFixed(2)}] mm<br>|E| = ${p.value[4].toFixed(2)} dB` : "" },
      grid: { left: 52, right: 70, top: 10, bottom: 34 },
      xAxis: { type: "value", min: ue[0], max: ue[ue.length - 1], name: `${slice.u_axis} (mm)`,
               nameTextStyle: { color: fg }, axisLabel: { color: fg }, splitLine: { show: false } },
      yAxis: { type: "value", min: ve[0], max: ve[ve.length - 1], name: `${slice.v_axis} (mm)`,
               nameTextStyle: { color: fg }, axisLabel: { color: fg }, splitLine: { show: false } },
      visualMap: { type: "continuous", min: vmin ?? -40, max: 0, dimension: 4, seriesIndex: 0,
                   right: 4, top: "middle", calculable: true, text: ["0 dB", `${vmin ?? -40} dB`],
                   textStyle: { color: fg },
                   inRange: { color: HEAT_BAND } },
      series,
    }, true); // notMerge：复用路径整体替换旧 option
    bindChartResize(el); // P0-5：resize 去重（WeakSet 标记）
    // W3-B：plotCard 级导出面——custom 矩形系列 + visualMap 不在 plotcard
    // builder 能力面，渲染管线保留自研，仅补导出（共用工厂）；
    // CSV=宽表（x=u_mm，每行 v_mm 一列）——热图网格的自然 2D 矩阵形态
    chartExportTools(el.parentElement, el, {
      name: "field-slice-" + slice.axis + slice.index,
      getChart: () => chart,
      getCsvSeries: () => slice.values.map((row, j) => ({
        name: slice.v_axis + "=" + slice.v_mm[j] + "mm",
        x: slice.u_mm, y: row,
      })),
    });
    return chart;
  } catch (e) {
    el.innerHTML = `<span style="color:var(--err)">slice error: ${esc(e.message)}</span>`;
    return null;
  }
}

/* PyVista 等值面三角网 → three.js（顶点按 dB 着色；无 PyVista 时服务层不给此块） */
function drawIsoMesh(container, iso) {
  const THREE = T.THREE;
  // P0-4：本管线 renderer 自登记（_isoRenderers）——重建前完全释放上一代
  // （停动画循环 → dispose → forceContextLoss）；容器被 pageField 换血的
  // 场景由 load() 里的 releaseWebGLIn(isoEl) 兜底。
  const prevR = _isoRenderers.get(container);
  if (prevR) {
    prevR.setAnimationLoop(null);
    prevR.dispose();
    if (prevR.forceContextLoss) prevR.forceContextLoss();
    _isoRenderers.delete(container);
  }
  container.innerHTML = "";
  const w = container.clientWidth || 600, h = 380;
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);
  _isoRenderers.set(container, renderer);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d1118);
  const camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 5000);
  const verts = iso.vertices_mm, faces = iso.faces, vdb = iso.vertex_db || [];
  const c = [0, 0, 0];
  for (const p of verts) for (let i = 0; i < 3; i++) c[i] += p[i] / verts.length;
  const pos = new Float32Array(verts.length * 3), col = new Float32Array(verts.length * 3);
  const lo = Math.min(...iso.levels_db, -1), tmp = new THREE.Color();
  verts.forEach((p, i) => {
    // 场景坐标：x→x, z→上, y→深度（与 drawBoxes 一致）
    pos[3 * i] = p[0] - c[0]; pos[3 * i + 1] = p[2] - c[2]; pos[3 * i + 2] = p[1] - c[1];
    const t = Math.max(0, Math.min(1, ((vdb[i] ?? lo) - lo) / (0 - lo)));
    tmp.setHSL(0.66 * (1 - t), 0.9, 0.5);
    col[3 * i] = tmp.r; col[3 * i + 1] = tmp.g; col[3 * i + 2] = tmp.b;
  });
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
  geo.setIndex(faces.flat());
  geo.computeVertexNormals();
  const mesh = new THREE.Mesh(geo, new THREE.MeshPhongMaterial({
    vertexColors: true, side: THREE.DoubleSide, transparent: true, opacity: 0.85 }));
  scene.add(mesh);
  scene.add(new THREE.AmbientLight(0xffffff, 0.6));
  const dl = new THREE.DirectionalLight(0xffffff, 0.9);
  dl.position.set(80, 120, 60);
  scene.add(dl);
  const bbox = new THREE.Box3().setFromObject(mesh);
  const maxDim = Math.max(bbox.max.x - bbox.min.x, bbox.max.y - bbox.min.y, bbox.max.z - bbox.min.z, 10);
  scene.add(new THREE.GridHelper(maxDim * 2, 20, 0x242c3d, 0x242c3d));
  let dragging = false, px = 0, py = 0, theta = 0.7, phi = 1.05, radius = maxDim * 1.9;
  const apply = () => {
    camera.position.set(radius * Math.sin(phi) * Math.cos(theta), radius * Math.cos(phi),
                        radius * Math.sin(phi) * Math.sin(theta));
    camera.lookAt(0, 0, 0);
  };
  apply();
  const dom = renderer.domElement;
  dom.onpointerdown = (e) => { dragging = true; px = e.clientX; py = e.clientY; };
  dom.onpointerup = () => (dragging = false);
  dom.onpointermove = (e) => {
    if (!dragging) return;
    theta += (e.clientX - px) * 0.008; phi -= (e.clientY - py) * 0.008;
    phi = Math.max(0.1, Math.min(3.0, phi)); px = e.clientX; py = e.clientY; apply();
  };
  dom.onwheel = (e) => { e.preventDefault(); radius *= e.deltaY > 0 ? 1.1 : 0.9; apply(); };
  renderer.setAnimationLoop(() => renderer.render(scene, camera));
  const legend = document.createElement("div");
  legend.className = "legend3d";
  legend.innerHTML = `<span class='muted'>等值面 ${iso.levels_db.join("/")} dB（相对峰值）· ${iso.n_vertices} 顶点 / ${iso.n_faces} 三角 · 顶点色=dB（蓝低→红高）· 拖动旋转 / 滚轮缩放</span>`;
  container.appendChild(legend);
}

/* 远场 3D 方向图（farfield_3d.h5）：θ×φ 热图（D4 联动，极坐标切面在「远场方向图」页） */
function drawPattern3d(el, p) {
  try {
    const light = bodyIsLight();
    const fg = themePick(light, THEME_COLORS.fg);
    const data = [];
    p.db.forEach((row, ti) => row.forEach((v, pi) => data.push([pi, ti, v])));
    const chart = echartsInitCached(el); // P0-5：实例缓存守卫（清容器移入新建路径）
    el.style.height = "300px";
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { formatter: (q) => `θ=${p.theta_deg[q.value[1]]}° φ=${p.phi_deg[q.value[0]]}°<br>${q.value[2].toFixed(2)} dB` },
      grid: { left: 52, right: 70, top: 10, bottom: 34 },
      xAxis: { type: "category", data: p.phi_deg, name: "φ (deg)", nameTextStyle: { color: fg }, axisLabel: { color: fg } },
      yAxis: { type: "category", data: p.theta_deg, name: "θ (deg)", nameTextStyle: { color: fg }, axisLabel: { color: fg } },
      visualMap: { type: "continuous", min: -40, max: 0, right: 4, top: "middle", calculable: true,
                   textStyle: { color: fg },
                   inRange: { color: HEAT_BAND } },
      series: [{ type: "heatmap", data, animation: false, progressive: 2000 }],
    }, true); // notMerge：复用路径整体替换旧 option
    bindChartResize(el); // P0-5：resize 去重（WeakSet 标记）
    // W3-B：plotCard 级导出面——heatmap + visualMap 不在 plotcard builder
    // 能力面，渲染管线保留自研，仅补导出（共用工厂）；
    // CSV=宽表（x=φ°，每行 θ° 一列）
    chartExportTools(el.parentElement, el, {
      name: "farfield-3d-heatmap",
      getChart: () => chart,
      getCsvSeries: () => p.db.map((row, ti) => ({
        name: "θ=" + p.theta_deg[ti] + "°（x=φ°）",
        x: p.phi_deg, y: row,
      })),
    });
  } catch (e) {
    el.innerHTML = `<span style="color:var(--err)">pattern error: ${esc(e.message)}</span>`;
  }
}

export async function pageField() {
  const v = T.$("view-field");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>数据源 = openEMS 真跑 run 的 DumpHDF5 产物：nf2ff 盒六面 nf2ff_E_*.h5（时域包络 max|E(t)|）、SAR_raw.h5（频域 |E(f0)|）、SAR_1g.h5（标量 SAR 体）。</li>
      <li>切片：三轴中面 |E| 热图（dB 相对体峰值，单元格按真实 mm 网格绘制），拖滑块改切片索引；等值线 −3/−10/−20 dB 叠加（可改）。</li>
      <li>等值面：安装 extras <code>rfauto[viz3d]</code>（PyVista/VTK）后为三角网 3D（three.js 渲染）；未安装时诚实降级为切片等值线（engine 标签可见）。</li>
      <li>远场 3D 图（farfield_3d.h5，θ×φ 热图）与 D4 指标（farfield_meta.json）联动；「→ 远场极坐标页」跳到同一 run 的极坐标切面。</li>`) +
    `<h2 class='page'>场可视化 3D<small>DumpHDF5 切片 / 等值面 / 远场 3D</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='fv-run' style='max-width:300px'></select>
         <b>dump</b><select id='fv-dump' style='max-width:220px'></select>
         <b>等值线 dB</b><input id='fv-levels' value='-3,-10,-20' style='width:110px'>
         <button class='minor' id='fv-reload'>刷新</button>
         <button class='minor' id='fv-polar'>→ 远场极坐标页</button>
         <span id='fv-info' class='muted'></span></div>
       <div id='fv-metrics' class='toolbar' style='flex-wrap:wrap;gap:14px'></div>
       <div id='fv-slices'></div>
       <div id='fv-iso'></div>
       <div id='fv-pattern'></div>
     </div>`;
  const listing = await T.api("/api/field");
  const runs = listing.runs || [];
  const sel = T.$("fv-run"), dsel = T.$("fv-dump");
  if (!runs.length) {
    sel.innerHTML = "<option>（无场 dump run）</option>";
    T.$("fv-info").textContent = "先用 openEMS 通道以 far_field=True / sar=True 真跑 patch/dipole 模板（nf2ff 盒面 dump 即可）";
    return;
  }
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.n_dumps)} dump${r.has_farfield_h5 ? " · 远场3D" : ""}）</option>`).join("");
  if (S.fvRunId) sel.value = S.fvRunId;
  const fillDumps = () => {
    const r = runs.find((x) => x.run_id === sel.value) || runs[0];
    dsel.innerHTML = r.dumps.map((d) => `<option value='${escAttr(d)}'>${esc(d)}</option>`).join("");
    if (S.fvDump && r.dumps.includes(S.fvDump)) dsel.value = S.fvDump;
  };
  fillDumps();
  const sliceIdx = {};

  async function load() {
    S.fvRunId = sel.value; S.fvDump = dsel.value;
    const q = new URLSearchParams({ dump: dsel.value, levels: T.$("fv-levels").value });
    for (const [ax, i] of Object.entries(sliceIdx)) q.set(`s${ax}`, i);
    const d = await T.api(`/api/field/${encodeURIComponent(sel.value)}?${q}`);
    const info = T.$("fv-info");
    if (!d.ok) { info.textContent = (d.errors || []).join("; "); return; }
    const vol = d.volume;
    info.innerHTML = `${vol.shape.join("×")} · ${esc(vol.domain)}${vol.frequency_ghz ? " · f=" + vol.frequency_ghz.toFixed(4) + " GHz" : ""}` +
      `${vol.n_timesteps ? " · " + vol.n_timesteps + " 步包络" : ""} · 峰值 ${Number(vol.peak).toExponential(3)} · ` +
      `引擎 <b>${esc(d.engine)}</b>${listing.viz3d_available ? "" : "（PyVista 未装，等值面降级为等值线）"}` +
      (d.warnings.length ? `<br><span style='color:var(--err)'>${esc(d.warnings.join("；"))}</span>` : "");
    // D4 指标联动
    const m = d.farfield_metrics;
    const fmt = (x, unit, digits = 2) => (x === null || x === undefined || Number.isNaN(+x)) ? "N/A" : `${(+x).toFixed(digits)}${unit}`;
    T.$("fv-metrics").innerHTML = m ? [
      `模板 <b>${esc(m.template || "?")}</b>`, `f_res <b>${fmt(m.f_res_ghz, " GHz", 3)}</b>`,
      `方向性 <b>${fmt(m.dmax_dbi, " dBi")}</b>`, `峰值增益 <b>${fmt(m.gain_max_dbi, " dBi")}</b>`,
      `辐射效率 <b>${fmt(m.efficiency === null || m.efficiency === undefined ? null : m.efficiency * 100, "%", 1)}</b>`,
      // PEC 地镜像修正因子 + patch 族 η 门（服务层 correct_pec_mirror/patch_eta_gate 判读，此处只渲染）
      ...(m.pec_mirror_factor && m.pec_mirror_factor !== 1 ? [`镜像修正 <b>Prad÷${esc(m.pec_mirror_factor)}</b>`] : []),
      ...(m.eta_gate ? [`η 门 <b style='color:var(${m.eta_gate.ok === null ? "--muted" : m.eta_gate.ok ? "--ok" : "--err"})'>${m.eta_gate.ok === null ? "N/A" : m.eta_gate.ok ? "PASS" : "FAIL"}</b> [${esc(m.eta_gate.gate.join(", "))}]`] : []),
    ].map((s) => `<span>${s}</span>`).join("") : `<span class='muted'>（无 farfield_meta.json：D4 指标不可用）</span>`;
    // 切片 + 等值线叠加（降级引擎给每个中面的线段；索引改变后重新取）
    const iso = d.isosurface || {};
    const byAxis = {};
    for (const c of iso.contours || []) {
      byAxis[c.axis] = c.segments.map((s) => ({ ...s,
        _levelIndex: iso.levels_linear.indexOf(s.level),
        level_db: iso.levels_db[iso.levels_linear.indexOf(s.level)] }));
    }
    const box = T.$("fv-slices");
    disposeChartsIn(box); // P0-5：子树重建前释放挂在旧切片容器上的 echarts 实例
    box.innerHTML = d.slices.map((s) =>
      `<div style='margin-bottom:var(--space-2)'><b class='muted'>${esc(s.axis)} = ${esc(s.position_mm)} mm 切面（${esc(s.u_axis)}×${esc(s.v_axis)}，索引 ${esc(s.index)}/${esc(s.n - 1)}）</b>
         <input type='range' id='fv-s-${escAttr(s.axis)}' min='0' max='${escAttr(s.n - 1)}' value='${escAttr(s.index)}' data-ax='${escAttr(s.axis)}' style='width:220px;vertical-align:middle'>
         <div id='fv-sl-${s.axis}'></div></div>`).join("");
    let vmin = -20;
    for (const s of d.slices) for (const row of s.values) for (const x of row) if (x < vmin) vmin = x;
    vmin = Math.max(-60, vmin);
    for (const s of d.slices) {
      const sameIdx = (iso.contours || []).find((c) => c.axis === s.axis && c.index === s.index);
      drawFieldSlice(T.$(`fv-sl-${s.axis}`), s, sameIdx ? byAxis[s.axis] : [], Math.floor(vmin));
    }
    box.querySelectorAll("input[type=range]").forEach((r) => {
      r.onchange = () => { sliceIdx[r.dataset.ax] = +r.value; load(); };
    });
    // 等值面（PyVista）或降级说明
    const isoEl = T.$("fv-iso");
    releaseWebGLIn(isoEl); // P0-4：等值面容器换血前释放旧 renderer/上下文
    if (iso.ok && iso.engine === "pyvista" && iso.n_faces > 0) {
      isoEl.innerHTML = `<b class='muted'>等值面（PyVista/VTK 移动立方体）</b><div id='fv-iso-3d'></div>`;
      drawIsoMesh(T.$("fv-iso-3d"), iso);
    } else if (iso.ok) {
      isoEl.innerHTML = `<div class='muted' style='margin:6px 0'>等值面引擎 ${esc(iso.engine)}：电平 ${esc(iso.levels_db.join("/"))} dB 已作为等值线叠加在切片热图上（白/黄/橙 = 低→高电平）。安装 <code>rfauto[viz3d]</code> 可得三角网 3D 等值面。</div>`;
    } else {
      isoEl.innerHTML = `<div style='color:var(--err);margin:6px 0'>等值面失败：${esc((iso.errors || []).join("; "))}</div>`;
    }
    // 远场 3D 图（D4 联动）
    const pEl = T.$("fv-pattern");
    disposeChartsIn(pEl); // P0-5：远场 3D 图容器换血前释放旧实例
    if (d.pattern3d) {
      pEl.innerHTML = `<b class='muted'>远场 3D 方向图（${esc(d.pattern3d.source.split(/[\\/]/).pop())} · Dmax ${fmt(d.pattern3d.dmax_dbi, " dBi")} · f=${fmt(d.pattern3d.frequency_ghz, " GHz", 4)}）</b><div id='fv-pat'></div>`;
      drawPattern3d(T.$("fv-pat"), d.pattern3d);
    } else pEl.innerHTML = "<div class='muted'>（无 farfield_3d.h5/nf2ff.h5：远场 3D 图不可用）</div>";
  }
  sel.onchange = () => { fillDumps(); Object.keys(sliceIdx).forEach((k) => delete sliceIdx[k]); load(); };
  dsel.onchange = () => { Object.keys(sliceIdx).forEach((k) => delete sliceIdx[k]); load(); };
  T.$("fv-reload").onclick = load;
  T.$("fv-polar").onclick = () => { S.ffRunId = sel.value; showPage("farfield"); };
  await load();
}
