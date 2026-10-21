/* rfauto 场/远场可视化页族（架构批 UI-R2 自 pages.js 拆出，逐字节
   搬移）：远场极坐标（nf2ff）+ Smith 圆图（G9，S 参数页复用）+ 场切片
   热图/等值面/远场 3D（DumpHDF5）。W3-S12（R6 审计 P-5）：polar/Smith/
   custom/heatmap 四管线不在 plotcard builder 能力面，经 plotCard
   props.option 逃生舱接入壳（导出/复用/主题联动单源），option 构造保留
   自研；等值面 three.js 管线不动。
   i18n（发布前置软编码批 S1 全清）：壳/help 块分段 t()、指标行/切片头/
   等值面状态/aria 全迁词表（fieldviz.* 键域，zh 与旧字面逐字节同、en
   新增）——拼接数据段（run_id/模板名/引擎名/警告串）照旧 esc 后拼模板，
   词表值零 HTML；壳静态标签 data-i18n+applyI18nRoot 首扫（farfield/field
   两页各自 v 根）。series 名（φ=… pattern_db（x=θ°）等纯 ASCII/希腊记号）
   与图表错误前缀（polar error: 等协议形态）保留原文。 */

import { HEAT_BAND, ISO_BAND, THEME_COLORS, themePick } from "../theme.js";
import {
  _isoRenderers,
  disposeChartsIn,
  releaseWebGLIn,
  smithChartTheme, // UI-R5：Smith 网格/轨迹色对走 charts 层选项工厂
} from "./charts.js";
import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
// i18n（S1 全清）：壳静态标签 data-i18n+首扫；动态容器文案 t() 渲染期烘焙。
import { t, applyI18nRoot } from "./i18n.js";
import { showPage } from "./router.js";
// P8-9（架构批 W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本文件 4 点，
// 双视图键）——farfield 页数据面接 viewSignal("farfield")、field 页数据面接
// viewSignal("field")，切页收束 + aborted 短路（在途拉取不再写隐藏区）。
// 信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

/* ── 远场极坐标页（WP4.1/D4：nf2ff 方向图 + 增益/效率/SAR）───────────── */
let _fieldReload = null; // R-1：refresh 局部刷新转发登记（fieldCtx 消费，pageField 内赋值）

/* 页私有选中记忆（W6-S2 S 状态收编：原 S.ffRunId/S.fvRunId/S.fvDump 单模块
   私有键降级模块级——属主=本模块双页共壳，契约表见 context.js；_ffRunId
   跨页带值语义（fv-polar→farfield）不变）。 */
let _ffRunId = null;
let _fvRunId = null;
let _fvDump = null;

export async function pageFarfield() {
  const v = T.$("view-farfield");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("fieldviz.ff_help_1")}</li>
      <li>${t("fieldviz.ff_help_2")}</li>
      <li>${t("fieldviz.ff_help_3")}</li>
      <li>${t("fieldviz.ff_help_4")}</li>`) +
    `<h2 class='page'><span data-i18n='fieldviz.ff_title'>${t("fieldviz.ff_title")}</span><small data-i18n='fieldviz.ff_subtitle'>${t("fieldviz.ff_subtitle")}</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='ff-run' style='max-width:340px'></select>
         <span id='ff-info' class='muted'></span></div>
       <div id='ff-metrics' class='toolbar' style='flex-wrap:wrap;gap:14px'></div>
       <div id='ff-polar'></div>
       <div id='ff-sar'></div>
     </div>`;
  applyI18nRoot(v); // 壳静态标签首扫（S1 全清；幂等，动态容器走 t() 烘焙）
  const runsResp = await apiFetch("/api/farfield",
    { signal: viewSignal("farfield") });
  if (runsResp.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const runs = runsResp.runs || [];
  const sel = T.$("ff-run");
  if (!runs.length) {
    sel.innerHTML = "<option>" + t("fieldviz.ff_empty_opt") + "</option>";
    T.$("ff-info").textContent = t("fieldviz.ff_empty_info");
    return;
  }
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}${r.has_sar ? " ·SAR" : ""}</option>`).join("");
  if (_ffRunId) sel.value = _ffRunId;

  async function load() {
    _ffRunId = sel.value;
    const d = await apiFetch("/api/farfield/" + encodeURIComponent(sel.value),
      { signal: viewSignal("farfield") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    if (!d.ok) { T.$("ff-info").textContent = (d.errors || []).join("; "); return; }
    T.$("ff-info").textContent = t("fieldviz.tpl_label") + `${d.template || "?"} · f_res=${(d.metrics.f_res_ghz ?? 0).toFixed(3)} GHz`;
    const m = d.metrics || {};
    const fmt = (x, unit, digits = 2) => (x === null || x === undefined || Number.isNaN(+x))
      ? "N/A" : `${(+x).toFixed(digits)}${unit}`;
    T.$("ff-metrics").innerHTML = [
      t("fieldviz.m_dmax") + `<b>${fmt(m.dmax_dbi, " dBi")}</b>`,
      t("fieldviz.m_gain") + `<b>${fmt(m.gain_max_dbi, " dBi")}</b>`,
      t("fieldviz.m_eff") + `<b>${fmt(m.efficiency !== null && m.efficiency !== undefined ? m.efficiency * 100 : null, "%", 1)}</b>`,
      t("fieldviz.m_closure") + `<b>${fmt(m.power_budget_closure === null || m.power_budget_closure === undefined ? null : m.power_budget_closure * 100, "%", 2)}</b>`,
    ].concat(m.eta_gate ? [
      // patch 族 η 门（服务层 farfield_view 复用 patch_eta_gate 判读，此处只渲染，与场页同口径）
      t("fieldviz.m_eta_gate") + `<b style='color:var(${m.eta_gate.ok === null ? "--muted" : m.eta_gate.ok ? "--ok" : "--err"})'>${m.eta_gate.ok === null ? "N/A" : m.eta_gate.ok ? "PASS" : "FAIL"}</b> [${esc(m.eta_gate.gate.join(", "))}]`,
    ] : []).concat((m.sar && m.sar.ok !== false) ? [
      `SAR(1g) <b>${fmt(m.sar.sar_max_w_per_kg_per_1w_acc, " W/kg/W", 3)}</b>` + t("fieldviz.m_sar_acc"),
      t("fieldviz.m_absorbed") + `<b>${fmt(m.sar.absorbed_fraction === null || m.sar.absorbed_fraction === undefined ? null : m.sar.absorbed_fraction * 100, "%", 1)}</b>`,
    ] : []).map((s) => `<span>${s}</span>`).join("");
    // 极坐标切面（echarts polar：angleAxis=θ，radiusAxis=dB）
    const box = T.$("ff-polar");
    disposeChartsIn(box); // P0-5：子树重建前释放旧切面图实例（缓存键随元素走）
    box.innerHTML = (d.cuts || []).map((c, i) =>
      `<div style='margin-bottom:var(--space-2)'><b class='muted'>φ=${c.phi_deg}°` + t("fieldviz.cut_label") +
      t("fieldviz.cut_hpbw_pre") + `${c.hpbw_deg === null ? "N/A" : c.hpbw_deg.toFixed(1) + "°"} · ` +
      `F/B ${c.front_to_back_db === null ? "N/A" : c.front_to_back_db.toFixed(1) + " dB"}` + t("fieldviz.paren_close") + `</b>` +
      `<div id='ff-pol-${i}'></div></div>`).join("");
    (d.cuts || []).forEach((c, i) => {
      try {
        const el = T.$(`ff-pol-${i}`);
        // W3-S12（R6 审计 P-5）：plotCard 逃生舱迁移——原 echartsInitCached
        // 直调 + bindChartResize + chartExportTools 补丁面整体收编进壳
        // （CSV/PNG/SVG 导出钮+同容器复用+主题联动重放随壳内建；函数形态
        // option 在主题换档时以新档 ctx 现取，深浅配色一拍跟上）。
        // series=CSV 数据面（x=θ°，y=pattern_db，与旧 getCsvSeries 同构）。
        T.plotCard(el, {
          option: ({ light }) => ({
            backgroundColor: "transparent",
            tooltip: {},
            angleAxis: {
              type: "value", min: -180, max: 180, startAngle: 90,
              axisLine: { lineStyle: { color: themePick(light, THEME_COLORS.fieldAxisLine) } }, // UI-R12：THEME_COLORS 单源（原内联 #55607a 冻结迁移）
              axisLabel: { color: themePick(light, THEME_COLORS.fg) }, splitLine: { show: true },
            },
            radiusAxis: {
              min: -40, max: 0,
              axisLine: { lineStyle: { color: themePick(light, THEME_COLORS.fieldAxisLine) } }, // UI-R12：同上
              axisLabel: { color: themePick(light, THEME_COLORS.fg) }, splitLine: { show: true },
            },
            polar: {},
            series: [{
              type: "line", coordinateSystem: "polar", showSymbol: false,
              data: c.theta_deg.map((t, j) => [c.pattern_db[j], t]),
              lineStyle: { width: 1.8,
                color: themePick(light, THEME_COLORS.seriesBlue) },
            }],
          }),
          series: [{ name: `φ=${c.phi_deg}° pattern_db（x=θ°）`,
                     x: c.theta_deg, y: c.pattern_db }],
          height: "360px",
          exportName: "farfield-polar-phi" + c.phi_deg,
          ariaLabel: t("fieldviz.aria_chart") + `φ=${c.phi_deg}°` + t("fieldviz.polar_aria_mid") +
            `${c.hpbw_deg === null ? "N/A" : c.hpbw_deg.toFixed(1) + "°"}` + t("fieldviz.paren_close"),
        });
      } catch (e) {
        T.$(`ff-pol-${i}`).innerHTML = `<span style="color:var(--err)">polar error: ${esc(e.message)}</span>`;
      }
    });
    // SAR 块（有产物才渲染）
    T.$("ff-sar").innerHTML = (m.sar && m.sar.ok !== false)
      ? `<div class='muted' style='margin-top:6px'>` + t("fieldviz.sar_note_lead") +
        t("fieldviz.sar_f_pre") + `${(m.f_res_ghz ?? 0).toFixed(3)} GHz · ` +
        t("fieldviz.sar_note_raw_lead") + `${fmt(m.sar.sar_max_w_per_kg, " W/kg", 3)}` + t("fieldviz.sar_note_tail") + `</div>`
      : "";
  }
  sel.onchange = load;
  await load();
}

/* ═══ R-1（架构批 W4-S17）：PageContext 增量钩子 farfieldCtx ══════════
   refresh=当前 run 方向图/指标重拉（pageFarfield 幂等——壳判 innerHTML 已在
   即跳过，_ffRunId 选择态保留；plotCard 壳同容器复用换数据）。无轮询面，
   leave 不需要。 */
export const farfieldCtx = {
  refresh: () => pageFarfield(),
};

/* ── Smith 圆图（G9，S 参数页增强）：网格几何+轨迹全部来自服务层 JSON ── */
export function drawSmith(el, traces, grid, z0) {
  try {
    const size = Math.min(el.clientWidth || 560, 560);
    // W3-S12（R6 审计 P-5）：plotCard 逃生舱迁移——隐藏轴等比坐标 + 网格几何
    // 系列仍自研（不在 builder 能力面），但渲染/导出/主题联动全收进壳：
    // 函数形态 option 按档现取（smithChartTheme 工厂色对），width=height=方图
    // 等比（plotCard width 面新增）；series=CSV 数据面（每轨迹 Γ 实/虚部长表）。
    const csvSeries = traces.flatMap((t) => {
      const nm = t.label || t.name;
      return [
        { name: nm + " Re(Γ)", x: t.freq_ghz, y: t.re },
        { name: nm + " Im(Γ)", x: t.freq_ghz, y: t.im },
      ];
    });
    const chart = T.plotCard(el, {
      option: ({ light }) => {
        const fg = themePick(light, THEME_COLORS.fg);
        // UI-R5：网格/轨迹色对走 charts 层 smithChartTheme 工厂（色值单源仍在
        // theme.js smithPalette/smithGrid——工厂只做一对一次取齐）
        const { grid: gridColor, palette: colors } = smithChartTheme(light);
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
        return {
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
        };
      },
      series: csvSeries,
      width: `${size}px`, height: `${size}px`, // 方图等比（原 el 双向 style 同语义）
      exportName: "smith-chart",
      // PR-1 a11y：图像语义（轨迹名 + Z0 进 aria-label，读屏可闻；plotCard
      // 壳把 role=img/aria-label 落在图表容器 chartDiv 上）
      ariaLabel: t("fieldviz.smith_aria_lead") +
        `${(traces.map((tr) => tr.label || tr.name)).join("、") || t("fieldviz.smith_aria_none")}（Z0=${z0 ?? 50}Ω）`,
    });
    const note = document.createElement("div");
    note.className = "muted";
    note.style.marginTop = "4px";
    note.textContent = `Z0 = ${z0 ?? 50} Ω · ` + t("fieldviz.smith_note_grid") +
      `${(grid ? grid.r_circles.map((c) => c.r) : []).join("/")}` + t("fieldviz.smith_note_mid") +
      t("fieldviz.smith_note_trace");
    el.parentElement.appendChild(note);
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
    // W3-S12（R6 审计 P-5）：plotCard 逃生舱迁移——custom 矩形系列 + visualMap
    // 仍自研（不在 builder 能力面），导出/复用/主题联动收进壳（函数形态
    // option 按档现取）；series=CSV 数据面（宽表：x=u_mm，每行 v_mm 一列）。
    const levelColors = ISO_BAND; // UI-R12 任务3：等值线分档色单源（theme.js，冻结现值）
    const chart = T.plotCard(el, {
      option: ({ light }) => {
        const fg = themePick(light, THEME_COLORS.fg);
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
        for (const seg of contours || []) {
          const li = (seg._levelIndex ?? 0) % levelColors.length;
          series.push({ type: "line", data: seg.points, showSymbol: false, silent: true, animation: false,
                        name: `iso ${seg.level_db ?? ""} dB`,
                        lineStyle: { width: 1.2, color: levelColors[li] }, tooltip: { show: false } });
        }
        return {
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
        };
      },
      series: vals.map((row, j) => ({
        name: slice.v_axis + "=" + slice.v_mm[j] + "mm",
        x: slice.u_mm, y: row,
      })),
      height: "300px",
      exportName: "field-slice-" + slice.axis + slice.index,
      ariaLabel: t("fieldviz.aria_chart") + `${slice.axis}=${slice.position_mm}mm` +
        t("fieldviz.slice_aria_mid") + `${slice.u_axis}×${slice.v_axis}` + t("fieldviz.slice_aria_tail"),
    });
    return chart;
  } catch (e) {
    el.innerHTML = `<span style="color:var(--err)">slice error: ${esc(e.message)}</span>`;
    return null;
  }
}

/* PyVista 等值面三角网 → three.js（顶点按 dB 着色；无 PyVista 时服务层不给此块）
   P8-2（架构批 W3-S9，R1 §面1 重审）：T.THREE 同步取改调用点
   `await import("three")` 惰性取（app.js 顶层静态 import 与工具包 THREE 键
   已同批移除）——本函数改 async，唯一调用点（pageField.load 等值面分支）
   fire-and-forget 不消费返回值，行为等价；模块缓存命中后 await 立即返回。 */
async function drawIsoMesh(container, iso) {
  const THREE = await import("three");
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
  legend.innerHTML = `<span class='muted'>` + t("fieldviz.iso_legend_lead") + `${iso.levels_db.join("/")}` +
    t("fieldviz.iso_legend_mid") + `${iso.n_vertices}` + t("fieldviz.iso_legend_verts") + `${iso.n_faces}` +
    t("fieldviz.iso_legend_faces") + `</span>`;
  container.appendChild(legend);
}

/* 远场 3D 方向图（farfield_3d.h5）：θ×φ 热图（D4 联动，极坐标切面在「远场方向图」页） */
function drawPattern3d(el, p) {
  try {
    const data = [];
    p.db.forEach((row, ti) => row.forEach((v, pi) => data.push([pi, ti, v])));
    // W3-S12（R6 审计 P-5）：plotCard 逃生舱迁移——heatmap + visualMap 仍自研
    //（不在 builder 能力面），导出/复用/主题联动收进壳；series=CSV 数据面
    //（宽表：x=φ°，每行 θ° 一列）。
    T.plotCard(el, {
      option: ({ light }) => {
        const fg = themePick(light, THEME_COLORS.fg);
        return {
          backgroundColor: "transparent",
          tooltip: { formatter: (q) => `θ=${p.theta_deg[q.value[1]]}° φ=${p.phi_deg[q.value[0]]}°<br>${q.value[2].toFixed(2)} dB` },
          grid: { left: 52, right: 70, top: 10, bottom: 34 },
          xAxis: { type: "category", data: p.phi_deg, name: "φ (deg)", nameTextStyle: { color: fg }, axisLabel: { color: fg } },
          yAxis: { type: "category", data: p.theta_deg, name: "θ (deg)", nameTextStyle: { color: fg }, axisLabel: { color: fg } },
          visualMap: { type: "continuous", min: -40, max: 0, right: 4, top: "middle", calculable: true,
                       textStyle: { color: fg },
                       inRange: { color: HEAT_BAND } },
          series: [{ type: "heatmap", data, animation: false, progressive: 2000 }],
        };
      },
      series: p.db.map((row, ti) => ({
        name: "θ=" + p.theta_deg[ti] + "°（x=φ°）",
        x: p.phi_deg, y: row,
      })),
      height: "300px",
      exportName: "farfield-3d-heatmap",
      ariaLabel: t("fieldviz.pattern_aria"),
    });
  } catch (e) {
    el.innerHTML = `<span style="color:var(--err)">pattern error: ${esc(e.message)}</span>`;
  }
}

export async function pageField() {
  const v = T.$("view-field");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("fieldviz.help_1")}</li>
      <li>${t("fieldviz.help_2")}</li>
      <li>${t("fieldviz.help_3_lead")}<code>rfauto[viz3d]</code>${t("fieldviz.help_3_tail")}</li>
      <li>${t("fieldviz.help_4")}</li>`) +
    `<h2 class='page'><span data-i18n='fieldviz.title'>${t("fieldviz.title")}</span><small data-i18n='fieldviz.subtitle'>${t("fieldviz.subtitle")}</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='fv-run' style='max-width:300px'></select>
         <b>dump</b><select id='fv-dump' style='max-width:220px'></select>
         <b data-i18n='fieldviz.levels_label'>${t("fieldviz.levels_label")}</b><input id='fv-levels' value='-3,-10,-20' style='width:110px'>
         <button class='minor' id='fv-reload' data-i18n='fieldviz.reload'>${t("fieldviz.reload")}</button>
         <button class='minor' id='fv-polar' data-i18n='fieldviz.goto_polar'>${t("fieldviz.goto_polar")}</button>
         <span id='fv-info' class='muted'></span></div>
       <div id='fv-metrics' class='toolbar' style='flex-wrap:wrap;gap:14px'></div>
       <div id='fv-slices'></div>
       <div id='fv-iso'></div>
       <div id='fv-pattern'></div>
     </div>`;
  applyI18nRoot(v); // 壳静态标签首扫（S1 全清；幂等，动态容器走 t() 烘焙）
  const listing = await apiFetch("/api/field", { signal: viewSignal("field") });
  if (listing.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const runs = listing.runs || [];
  const sel = T.$("fv-run"), dsel = T.$("fv-dump");
  if (!runs.length) {
    sel.innerHTML = "<option>" + t("fieldviz.empty_opt") + "</option>";
    T.$("fv-info").textContent = t("fieldviz.empty_info");
    return;
  }
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}` + t("fieldviz.opt_pre") +
    `${esc(r.n_dumps)} dump${r.has_farfield_h5 ? t("fieldviz.opt_farfield") : ""}` +
    t("fieldviz.paren_close") + `</option>`).join("");
  if (_fvRunId) sel.value = _fvRunId;
  const fillDumps = () => {
    const r = runs.find((x) => x.run_id === sel.value) || runs[0];
    dsel.innerHTML = r.dumps.map((d) => `<option value='${escAttr(d)}'>${esc(d)}</option>`).join("");
    if (_fvDump && r.dumps.includes(_fvDump)) dsel.value = _fvDump;
  };
  fillDumps();
  const sliceIdx = {};

  async function load() {
    _fvRunId = sel.value; _fvDump = dsel.value;
    const q = new URLSearchParams({ dump: dsel.value, levels: T.$("fv-levels").value });
    for (const [ax, i] of Object.entries(sliceIdx)) q.set(`s${ax}`, i);
    const d = await apiFetch(`/api/field/${encodeURIComponent(sel.value)}?${q}`,
      { signal: viewSignal("field") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const info = T.$("fv-info");
    if (!d.ok) { info.textContent = (d.errors || []).join("; "); return; }
    const vol = d.volume;
    info.innerHTML = `${vol.shape.join("×")} · ${esc(vol.domain)}${vol.frequency_ghz ? " · f=" + vol.frequency_ghz.toFixed(4) + " GHz" : ""}` +
      `${vol.n_timesteps ? " · " + vol.n_timesteps + t("fieldviz.info_steps") : ""}` + t("fieldviz.info_peak") + `${Number(vol.peak).toExponential(3)} · ` +
      t("fieldviz.info_engine") + `<b>${esc(d.engine)}</b>${listing.viz3d_available ? "" : t("fieldviz.info_noviz3d")}` +
      (d.warnings.length ? `<br><span style='color:var(--err)'>${esc(d.warnings.join("；"))}</span>` : "");
    // D4 指标联动
    const m = d.farfield_metrics;
    const fmt = (x, unit, digits = 2) => (x === null || x === undefined || Number.isNaN(+x)) ? "N/A" : `${(+x).toFixed(digits)}${unit}`;
    T.$("fv-metrics").innerHTML = m ? [
      t("fieldviz.tpl_label") + `<b>${esc(m.template || "?")}</b>`, `f_res <b>${fmt(m.f_res_ghz, " GHz", 3)}</b>`,
      t("fieldviz.m_dmax") + `<b>${fmt(m.dmax_dbi, " dBi")}</b>`, t("fieldviz.m_gain") + `<b>${fmt(m.gain_max_dbi, " dBi")}</b>`,
      t("fieldviz.m_eff") + `<b>${fmt(m.efficiency === null || m.efficiency === undefined ? null : m.efficiency * 100, "%", 1)}</b>`,
      // PEC 地镜像修正因子 + patch 族 η 门（服务层 correct_pec_mirror/patch_eta_gate 判读，此处只渲染）
      ...(m.pec_mirror_factor && m.pec_mirror_factor !== 1 ? [t("fieldviz.m_mirror") + `<b>Prad÷${esc(m.pec_mirror_factor)}</b>`] : []),
      ...(m.eta_gate ? [t("fieldviz.m_eta_gate") + `<b style='color:var(${m.eta_gate.ok === null ? "--muted" : m.eta_gate.ok ? "--ok" : "--err"})'>${m.eta_gate.ok === null ? "N/A" : m.eta_gate.ok ? "PASS" : "FAIL"}</b> [${esc(m.eta_gate.gate.join(", "))}]`] : []),
    ].map((s) => `<span>${s}</span>`).join("") : `<span class='muted'>${t("fieldviz.no_farfield_meta")}</span>`;
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
      `<div style='margin-bottom:var(--space-2)'><b class='muted'>${esc(s.axis)} = ${esc(s.position_mm)} mm` + t("fieldviz.slice_head_mid") +
      `${esc(s.u_axis)}×${esc(s.v_axis)}` + t("fieldviz.slice_head_idx") + `${esc(s.index)}/${esc(s.n - 1)}` + t("fieldviz.paren_close") + `</b>
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
      isoEl.innerHTML = `<b class='muted'>${t("fieldviz.iso_head")}</b><div id='fv-iso-3d'></div>`;
      drawIsoMesh(T.$("fv-iso-3d"), iso);
    } else if (iso.ok) {
      isoEl.innerHTML = `<div class='muted' style='margin:6px 0'>` + t("fieldviz.iso_degrade_engine") + `${esc(iso.engine)}` +
        t("fieldviz.iso_degrade_levels") + `${esc(iso.levels_db.join("/"))} dB` + t("fieldviz.iso_degrade_body") +
        `<code>rfauto[viz3d]</code>` + t("fieldviz.iso_degrade_tail") + `</div>`;
    } else {
      isoEl.innerHTML = `<div style='color:var(--err);margin:6px 0'>` + t("fieldviz.iso_fail") + `${esc((iso.errors || []).join("; "))}</div>`;
    }
    // 远场 3D 图（D4 联动）
    const pEl = T.$("fv-pattern");
    disposeChartsIn(pEl); // P0-5：远场 3D 图容器换血前释放旧实例
    if (d.pattern3d) {
      pEl.innerHTML = `<b class='muted'>` + t("fieldviz.pattern_head_lead") +
        `${esc(d.pattern3d.source.split(/[\\/]/).pop())} · Dmax ${fmt(d.pattern3d.dmax_dbi, " dBi")} · f=${fmt(d.pattern3d.frequency_ghz, " GHz", 4)}` +
        t("fieldviz.paren_close") + `</b><div id='fv-pat'></div>`;
      drawPattern3d(T.$("fv-pat"), d.pattern3d);
    } else pEl.innerHTML = "<div class='muted'>" + t("fieldviz.no_pattern") + "</div>";
  }
  sel.onchange = () => { fillDumps(); Object.keys(sliceIdx).forEach((k) => delete sliceIdx[k]); load(); };
  dsel.onchange = () => { Object.keys(sliceIdx).forEach((k) => delete sliceIdx[k]); load(); };
  T.$("fv-reload").onclick = load;
  T.$("fv-polar").onclick = () => { _ffRunId = sel.value; showPage("farfield"); };
  _fieldReload = load; // R-1：refresh 局部刷新转发登记（fieldCtx 消费）
  await load();
}

/* ═══ R-1（架构批 W4-S17）：PageContext 增量钩子 fieldCtx ═════════════
   refresh=当前 run/dump 的切片/等值面/远场 3D 重拉——load 闭包经模块级引用
   转发（sparams/campaign 同款模式）+ 未进页 null 守卫；走 load 而非
   pageField 整体重进=切片滑条索引（sliceIdx）与 dump/run 选择态保留。
   无轮询面，leave 不需要。 */
export const fieldCtx = {
  refresh: async () => { const f = _fieldReload; if (f) f(); },
};
