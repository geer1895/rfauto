/* PR-3 PlotCard 组件化（规格 §D-8，2026-10-02 批）：drawEChart 的卡片壳。
   结构（option 单源）：
   - buildEChartOption：纯函数——迁移前 app.js drawEChart 的 option 构造
     逐字迁移于此（golden 快照 runs/pr34/golden_option_snapshot.json 钉等价，
     tests/unit/test_ui_plotcard.py 断言）；app.js drawEChart 与本文件的
     plotCard 共用同一 builder——「同数据同 option」由单源保证。
     在 base 之上按 props 增量（全部 gated，不传即与迁移前逐字节相同）：
       opts.crosshair  → tooltip.axisPointer cross（十字线读数）
       opts.y2 + 系列条目 y2:true → yAxis 数组 + yAxisIndex（双 y 轴）
       opts.mode:"convergence" → best-so-far 阶梯线 + 终值 markLine + 末点
   - bestSoFar / toCsv：收敛阶梯与 CSV 平铺的纯函数（node 行为钉可测）。
   - plotCard：DOM 壳（工具条 CSV/PNG 导出按钮 + 图表容器），浏览器侧。
   迁移面：pages.js 全部 drawEChart 调用点换壳为本组件；drawLineChart /
   Smith / 3D 自研管线不动。主题三态沿用 PR-1（body.light 类 + 调色板入参）。 */
import { esc } from "./pages.js";

/* 主题分档调色板由 app.js 传入（CHART_COLORS 单源在 app.js，对比度钉在彼处）。 */

/* 迁移前 drawEChart 的 option 构造（含 PR-3 gated 增量）。
   theme={light:boolean, palette:string[]}——缺省深色档+空调色板（测试友好）。 */
export function buildEChartOption(series, opts = {}, theme) {
  const t = theme || { light: false, palette: [] };
  const light = !!t.light;
  const fg = light ? "#1b2330" : "#dce3ee";
  // PR-1 对比度：轴线=理解图形所需（≥3:1），刻度文字=文本（≥4.5:1）；
  // 分隔线=装饰性网格（读数靠轴线+刻度），不参与硬门。
  const axis = { axisLine: { lineStyle: { color: light ? "#7f899d" : "#5f6a80" } },
                 axisLabel: { color: light ? "#5b6780" : "#8391a7" },
                 splitLine: { lineStyle: { color: light ? "#e7ebf2" : "#1c2331" } } };
  // PR-3 双 y 轴：y2 给出副轴名（字符串）即开；不传保持单 yAxis 对象（等价）。
  const yAxisSingle = { type: "value", scale: true, ...axis,
                        name: opts.ylabel || "", nameTextStyle: { color: fg } };
  const yAxis = opts.y2
    ? [yAxisSingle, { type: "value", scale: true, ...axis,
                      name: String(opts.y2), nameTextStyle: { color: fg },
                      splitLine: { show: false } }]
    : yAxisSingle;
  const option = {
    backgroundColor: "transparent",
    color: t.palette && t.palette.length ? t.palette : undefined,
    tooltip: Object.assign(
      { trigger: opts.xvalue ? "item" : "axis",
        valueFormatter: (v) => (+v).toFixed(2) },
      opts.crosshair ? { axisPointer: { type: "cross", label: { backgroundColor: "#6a7385" } } } : {}),
    legend: { top: 0, textStyle: { color: fg }, type: "scroll" },
    grid: { left: 52, right: 20, top: 34, bottom: 44 },
    xAxis: Object.assign(
      opts.xvalue
        ? { type: "value", scale: true }
        : { type: "category", data: series[0]?.x || [] },
      axis, { name: opts.xlabel || "", nameTextStyle: { color: fg } }),
    yAxis,
    dataZoom: opts.zoom === false ? [] : [
      { type: "inside" }, { type: "slider", height: 18, bottom: 6 }],
    series: series.flatMap((s) => {
      if (s.type === "scatter") return [{
        name: s.name, type: "scatter", data: s.data,
        itemStyle: { color: s.color, opacity: 0.85 },
        symbolSize: s.symbolSize || 10,
        markLine: opts.markline ? {
          silent: true, symbol: "none",
          lineStyle: { type: "dashed", color: light ? "#8a5300" : "#ffb74d" },
          data: opts.markline,
        } : undefined,
        ...(s.y2 ? { yAxisIndex: 1 } : {}),
      }];
      // 方差带（B3 批：explore GP σ 区间）：{type:"band", x, lower, upper,
      // color} → 两条 stack 线夹出 areaStyle 阴影带（基线透明不可交互）
      if (s.type === "band") {
        const stackId = `band-${Math.random().toString(36).slice(2, 8)}`;
        const xs = s.x || [];
        return [
          { type: "line", stack: stackId, data: s.lower,
            showSymbol: false, silent: true,
            lineStyle: { opacity: 0 }, emphasis: { disabled: true },
            tooltip: { show: false } },
          { name: s.name, type: "line", stack: stackId,
            data: (s.upper || []).map((u, i) => +u - +(s.lower?.[i] ?? 0)),
            showSymbol: false, silent: true,
            lineStyle: { opacity: 0 }, emphasis: { disabled: true },
            areaStyle: { color: s.color || "#4fc3f7", opacity: 0.18 },
            tooltip: { show: false } },
        ];
      }
      return [{
        name: s.name, type: "line", data: s.y, showSymbol: false,
        lineStyle: { width: 1.6, color: s.color },
        itemStyle: { color: s.color },
        markLine: opts.band ? {
          silent: true, symbol: "none", lineStyle: { type: "dashed", color: light ? "#8a5300" : "#ffb74d" },
          label: { color: light ? "#8a5300" : "#ffb74d", formatter: "带内" },
          data: [{ xAxis: opts.band[0] }, { xAxis: opts.band[1] }],
        } : undefined,
        ...(s.y2 ? { yAxisIndex: 1 } : {}),
      }];
    }),
  };
  // PR-3 收敛模式（gated）：best-so-far 阶梯线 + 终值 markLine + 末点。
  // cost 口径全仓一致「越低越好」——阶梯取 running min。
  if (opts.mode === "convergence") {
    const accent2 = light ? "#0e8f74" : "#22d3a5";
    const out = [];
    let k = 0;
    for (const s of series) {
      if (s.type === "band") { out.push(option.series[k], option.series[k + 1]); k += 2; continue; }
      const e = option.series[k];
      k += 1;
      if (!s.type && Array.isArray(s.y) && s.y.length) {
        const bs = bestSoFar(s.y);
        const last = s.y.length - 1;
        if (!e.markLine)
          e.markLine = {
            silent: true, symbol: "none",
            lineStyle: { type: "dashed", color: accent2 },
            label: { color: accent2, formatter: `best ${(+bs[last]).toFixed(3)}`, position: "insideEndTop" },
            data: [{ yAxis: bs[last] }],
          };
        e.markPoint = {
          symbol: "circle", symbolSize: 8,
          itemStyle: { color: accent2 },
          label: { color: fg, formatter: ({ value }) => (+value).toFixed(3), position: "top" },
          data: [[opts.xvalue ? (s.x ? s.x[last] : last) : last, s.y[last]]],
        };
        out.push(e, {
          name: `${s.name || "y"} best-so-far`,
          type: "line", data: bs, step: "end", showSymbol: false,
          lineStyle: { type: "dashed", width: 1.4, color: accent2 },
          itemStyle: { color: accent2 }, z: 3,
        });
        continue;
      }
      out.push(e);
    }
    option.series = out;
  }
  return option;
}

/* 收敛阶梯（纯函数）：running min（cost 越低越好，全仓口径）。 */
export function bestSoFar(ys) {
  const out = [];
  let cur = Infinity;
  for (const v of ys || []) {
    const n = +v;
    if (!Number.isNaN(n) && n < cur) cur = n;
    out.push(cur === Infinity ? null : cur);
  }
  return out;
}

/* CSV 平铺（纯函数）：线族（共享同一 x 网）→ 宽表 [x, 系列...]；
   散点（data=[[x,y],...]）或 x 网不齐 → 长表 [series,x,y]。
   band 是合成的阴影带不是数据，不导出。 */
export function toCsv(series) {
  const ss = (series || []).filter((s) => s.type !== "band");
  if (!ss.length) return "";
  const q = (v) => {
    const t = v == null ? "" : String(v);
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const isXY = (s) => Array.isArray(s.data) && s.data.length > 0 && Array.isArray(s.data[0]);
  const sameX = (a, b) => Array.isArray(a) && Array.isArray(b) &&
    a.length === b.length && a.every((v, i) => v === b[i]);
  if (ss.every((s) => !isXY(s))) {
    const x0 = ss[0].x || ss[0].y.map((_, i) => i);
    if (ss.slice(1).every((s) => sameX(s.x || s.y.map((_, i) => i), x0))) {
      const rows = [["x", ...ss.map((s) => s.name || "y")]];
      x0.forEach((x, i) =>
        rows.push([x, ...ss.map((s) => (s.y || [])[i] ?? "")]));
      return rows.map((r) => r.map(q).join(",")).join("\r\n");
    }
  }
  const rows = [["series", "x", "y"]];
  for (const s of ss) {
    if (isXY(s)) {
      for (const [x, y] of s.data) rows.push([s.name || "y", x, y]);
    } else {
      const xs = s.x || (s.y || []).map((_, i) => i);
      (s.y || []).forEach((y, i) => rows.push([s.name || "y", xs[i], y]));
    }
  }
  return rows.map((r) => r.map(q).join(",")).join("\r\n");
}

/* PlotCard 的 option（props 与 drawEChart opts 同形 + mode/crosshair/y2 增量）。 */
export function plotCardOption(props, theme) {
  return buildEChartOption(props.series || [], props, theme);
}

function downloadFile(name, content, mime) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type: mime }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* PlotCard：图表卡片壳（工具条 CSV/PNG 导出 + 图表容器）。
   props={series, xlabel, ylabel, y2?, markline, band, xvalue, zoom, height,
          title?, mode?:"line"|"convergence", crosshair?, exportCsv?, exportPng?,
          exportName?, ariaLabel?}；
   ctx={light:boolean, palette:string[]}（app.js 按 body.light 现取注入）。
   返回 echarts 实例（失败返 null 并把错误写进容器——不静默吞错，#135）。 */
export function plotCard(el, props = {}, ctx = {}) {
  try {
    const light = !!ctx.light;
    el.classList.add("plotcard");
    el.innerHTML = "";
    const tools = document.createElement("div");
    tools.className = "plotcard-tools";
    if (props.title) {
      const t = document.createElement("b");
      t.className = "plotcard-title";
      t.textContent = String(props.title);
      tools.appendChild(t);
    }
    const spacer = document.createElement("span");
    spacer.className = "plotcard-spacer";
    tools.appendChild(spacer);
    if (props.exportCsv !== false) {
      const b = document.createElement("button");
      b.className = "minor plotcard-btn";
      b.textContent = "CSV";
      b.title = "导出数据（CSV 平铺）";
      b.setAttribute("aria-label", "导出图表数据 CSV");
      b.onclick = () => downloadFile(
        `${props.exportName || "plotcard"}.csv`,
        "\ufeff" + toCsv(props.series), "text/csv;charset=utf-8");
      tools.appendChild(b);
    }
    if (props.exportPng !== false) {
      const b = document.createElement("button");
      b.className = "minor plotcard-btn";
      b.textContent = "PNG";
      b.title = "导出图片（PNG，2x）";
      b.setAttribute("aria-label", "导出图表图片 PNG");
      b.onclick = () => {
        if (!chart) return;
        const url = chart.getDataURL({
          type: "png", pixelRatio: 2,
          backgroundColor: light ? "#ffffff" : "#0d1118",
        });
        const a = document.createElement("a");
        a.href = url;
        a.download = `${props.exportName || "plotcard"}.png`;
        a.click();
      };
      tools.appendChild(b);
    }
    const chartDiv = document.createElement("div");
    chartDiv.className = "plotcard-chart";
    // PR-1 a11y：图表容器图像语义（与 app.js drawEChart 同构）
    chartDiv.setAttribute("role", "img");
    chartDiv.setAttribute("aria-label", props.ariaLabel ||
      `图表：${(props.series || []).map((s) => s.name).filter(Boolean).join("、") || "数据系列"}` +
      `${props.ylabel ? "，纵轴 " + props.ylabel : ""}${props.xlabel ? "，横轴 " + props.xlabel : ""}`);
    chartDiv.style.height = props.height || "280px";
    el.appendChild(tools);
    el.appendChild(chartDiv);
    const chart = window.echarts.init(chartDiv);
    chart.setOption(plotCardOption(props, { light, palette: ctx.palette || [] }));
    window.addEventListener("resize", () => chart.resize());
    return chart;
  } catch (e) {
    // 图表故障可见化——不静默吞错（排查 #135 教训）
    el.innerHTML = `<span style="color:var(--err)">plotcard error: ${esc(e.message)}</span>`;
    return null;
  }
}
