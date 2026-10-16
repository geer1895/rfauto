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
   - plotCard：DOM 壳（工具条 CSV/PNG/SVG 导出按钮 + 图表容器），浏览器侧。
   迁移面：pages.js 全部 drawEChart 调用点换壳为本组件；drawLineChart /
   Smith / 3D 自研管线不动。主题三态沿用 PR-1（body.light 类 + 调色板入参）。
   ═══ aurora_d UI-R5 增量 ═══
   - 万点级降采样（保形）：minmaxIndices（min-max 包络抽稀，峰值/谷值位置
     与数值逐位保持）+ 共享 x 网分组（多迹线同索引集，category 轴同步）；
     lttbIndices 为感知保形备选档；在 plotCardOption 接缝生效
     （buildEChartOption 保持纯构造不动，golden 钉不受扰）；阈值
     props.maxPoints > setDefaultMaxPoints > DEFAULT_MAX_POINTS；
     convergence 模式整跳（阶梯语义要全量 trial 序列）。
   - 调用面归一：plotCard 内建"同容器存活壳 setOption 复用"（charts.js
     W2-B 接口诉求落地）——旧 pages/charts.js plotCardCached 轮询包装降级
     为零破坏薄委托，全站图表渲染单一入口。
   - 导出统一：CSV/PNG/SVG 走 chart_export.js 单源出口（文件名
     `视图_指标_时间戳`），本文件私有 downloadFile 删除。 */
import { esc } from "./pages/dom.js"; // UI-R2：esc 单源直连（拆分前自 pages.js，与入口循环引用消除）
import { mkExportButtons } from "./chart_export.js"; // UI-R5：导出统一出口（CSV/PNG/SVG+时间戳命名）

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
        // W9-A：markPoint.data 项必须是 {value, coord:[x,y]} 对象——裸 [x,y]
        // 数组项在 echarts 5.6 会被 marker 归一化（emphasis/label 拷贝，minified
        // Co/cB 链）按"子项列表"展开，对数字基元做 .label 赋值 → 严格模式
        // TypeError "Cannot create property 'label' on number 'N'"（N=末点索引），
        // 整个 setOption 失败（tune 收敛图 P1-1 根因）。value 显式给出是为了
        // 末点标注 formatter 的 params.value 不为 undefined（coord 项不回填
        // value，SSR 实测）；标注与点位语义不变。
        e.markPoint = {
          symbol: "circle", symbolSize: 8,
          itemStyle: { color: accent2 },
          label: { color: fg, formatter: ({ value }) => (+value).toFixed(3), position: "top" },
          data: [{
            value: s.y[last],
            coord: [opts.xvalue ? (s.x ? s.x[last] : last) : last, s.y[last]],
          }],
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

/* ═══ aurora_d UI-R5：万点级曲线降采样（保形）═════════════════════════
   S 参数宽扫/多迹线可达数万频点——echarts 全量入 option 渲染与悬停读数
   随点数线性劣化。三件套：
   - minmaxIndices(ys, target)：min-max 包络抽稀（等间隔桶，每桶取 argmin+
     argmax，首末点恒保留）——**降采样前后峰值/谷值位置与数值逐位不变**：
     任何局部极值必是所在桶的桶极值，桶极值全数入选。这是保形默认档
     （Grafana/M3 同款选型）；高 Q 窄谷（宽于 1 样本、窄于桶宽）恰是 S 参数
     最关心的特征，感知类算法（LTTB）按三角形面积选点会整桶错过次深谷
     （实测 20001 点三谷曲线 LTTB 把 −25/−31dB 谷抹平成 −3dB 级，内部证据档），故不做默认。
   - lttbIndices(ys, n)：LTTB（Largest-Triangle-Three-Buckets）感知保形选点
     备选档（平滑曲线视觉等价性更好；不保证极值保留，导出供调用方自选）。
   - downsamplePlotSeries(series, cap)：共享 x 网分组——同图多迹线（同文件
     S11/S21/S22 共频网）必须用**同一索引集**（category 轴 data 取
     series[0].x，各迹线逐索引对齐；各迹线独立选点会选出不同点集错位）。
     索引集 = Σ各迹线 min-max（每迹线桶数预算 cap/2/迹线数），
     上界 cap + 2·迹线数。band（方差带）随同网格组一起抽（x/lower/upper
     同步，stack 差值语义不变）；scatter 不参与（Pareto 前沿逐点语义）。 */
export const DEFAULT_MAX_POINTS = 2000;

let _maxPoints = DEFAULT_MAX_POINTS;

/* 阈值可配（全站缺省；props.maxPoints 逐调用覆盖优先）。 */
export function setDefaultMaxPoints(n) {
  const v = Math.floor(+n);
  if (Number.isFinite(v) && v >= 3) _maxPoints = v;
  return _maxPoints;
}
export function getDefaultMaxPoints() {
  return _maxPoints;
}

/* LTTB 选点：返回升序索引数组（含首末；n≥长度或 n<3 → 全量）。 */
export function lttbIndices(ys, n) {
  const len = (ys || []).length;
  if (!len) return [];
  const target = Math.floor(+n);
  if (!Number.isFinite(target) || target < 3 || target >= len) {
    return [...ys.keys()];
  }
  const picked = [0];
  const bucket = (len - 2) / (target - 2);
  let a = 0;
  for (let i = 0; i < target - 2; i++) {
    const start = Math.floor((i + 1) * bucket) + 1;
    const end = Math.min(Math.floor((i + 2) * bucket) + 1, len - 1); // 末点独立保留
    const nStart = end;
    const nEnd = Math.min(Math.floor((i + 3) * bucket) + 1, len);
    // 第三点=下一桶平均（标准 LTTB）；空桶计数兜底（NaN 面积比较恒 false，
    // 落回 best=start——不会丢点只会退化取首）
    let ax = 0, ay = 0, cnt = 0;
    for (let j = nStart; j < nEnd; j++) { ax += j; ay += +ys[j] || 0; cnt += 1; }
    ax /= cnt || 1; ay /= cnt || 1;
    const ya = +ys[a] || 0;
    let best = start, bestArea = -1;
    for (let j = start; j < end; j++) {
      const area = Math.abs((a - ax) * (+ys[j] - ya) - (a - j) * (ay - ya));
      if (area > bestArea) { bestArea = area; best = j; }
    }
    picked.push(best);
    a = best;
  }
  picked.push(len - 1);
  return picked;
}

/* 全局极值索引（首个达成者；NaN 不参与——比较恒 false 自动跳过）。 */
function _argmax(ys) {
  let m = 0;
  for (let i = 1; i < ys.length; i++) if (+(ys[i]) > +(ys[m])) m = i;
  return m;
}
function _argmin(ys) {
  let m = 0;
  for (let i = 1; i < ys.length; i++) if (+(ys[i]) < +(ys[m])) m = i;
  return m;
}

/* min-max 包络抽稀（保形默认档）：target 点预算 → ⌊target/2⌋ 个等间隔桶，
   每桶 argmin+argmax 入选 + 首末点。返回升序去重索引数组（≤ target+2）。
   保形依据：任何局部极值必是所在桶的桶极值——桶极值全数入选即峰值/谷值
   位置与数值逐位保留（宽于 1 样本的窄谷不受桶宽影响）。 */
export function minmaxIndices(ys, target) {
  const len = (ys || []).length;
  if (!len) return [];
  const t = Math.floor(+target);
  if (!Number.isFinite(t) || t < 4 || t >= len) return [...ys.keys()];
  const nBuckets = Math.max(1, Math.floor(t / 2));
  const sel = new Set([0, len - 1]);
  const bw = (len - 2) / nBuckets;
  for (let b = 0; b < nBuckets; b++) {
    const start = Math.max(1, Math.floor(1 + b * bw));
    const end = Math.min(len - 1, Math.floor(1 + (b + 1) * bw));
    if (start >= end) continue;
    let iMax = start, iMin = start;
    for (let j = start; j < end; j++) {
      if (+(ys[j]) > +(ys[iMax])) iMax = j;
      if (+(ys[j]) < +(ys[iMin])) iMin = j;
    }
    sel.add(iMax);
    sel.add(iMin);
  }
  return [...sel].sort((a, b) => a - b);
}

/* 共享 x 网判同（先按 长度+首末 打键粗筛，候选组内逐元素精确比对）。 */
function _sameGrid(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

/* 分组降采样主入口（纯函数；无需抽的组原样保留，返回新数组不改入参）。 */
export function downsamplePlotSeries(series, cap) {
  const ss = Array.isArray(series) ? series : [];
  const limit = Math.floor(+cap);
  if (!Number.isFinite(limit) || limit < 3) return ss;
  const members = [];
  ss.forEach((s, i) => {
    const isLine = !s.type && Array.isArray(s.y);
    const isBand = s.type === "band" && Array.isArray(s.lower) && Array.isArray(s.upper);
    if (isLine || isBand) members.push(i);
  });
  if (!members.length) return ss;
  const groups = []; // { grid: x|null, len, idxs:[series 下标] }
  for (const i of members) {
    const s = ss[i];
    const grid = Array.isArray(s.x) ? s.x : null;
    const len = grid ? grid.length : (s.y || s.lower).length;
    const g = groups.find((g) => g.len === len &&
      ((g.grid === null && grid === null) ||
       (g.grid !== null && grid !== null && _sameGrid(g.grid, grid))));
    if (g) g.idxs.push(i);
    else groups.push({ grid, len, idxs: [i] });
  }
  const out = ss.slice();
  for (const g of groups) {
    if (g.len <= limit) continue;
    // 每迹线 min-max 桶预算=limit/迹线数（band 只搭车不占预算）；各迹线
    // 独立桶极值取并集后总点数上界 limit + 2·迹线数（桶极值跨迹线常重合，
    // 实际远小于上界）。
    const nData = g.idxs.filter((i) => !ss[i].type).length || 1;
    const per = Math.max(4, Math.floor(limit / nData));
    const sel = new Set();
    for (const i of g.idxs) {
      const s = ss[i];
      const ysList = s.type === "band" ? [s.upper, s.lower] : [s.y];
      for (const ys of ysList) {
        for (const id of minmaxIndices(ys, per)) sel.add(id);
      }
    }
    const ids = [...sel].sort((a, b) => a - b);
    const pick = (arr) => (Array.isArray(arr) ? ids.map((j) => arr[j]) : arr);
    for (const i of g.idxs) {
      const s = ss[i];
      const r = { ...s };
      if (Array.isArray(s.x)) r.x = pick(s.x);
      if (s.type === "band") { r.lower = pick(s.lower); r.upper = pick(s.upper); }
      else r.y = pick(s.y);
      out[i] = r;
    }
  }
  return out;
}

/* PlotCard 的 option（props 与 drawEChart opts 同形 + mode/crosshair/y2 增量；
   UI-R5：接缝处套降采样——buildEChartOption 保持纯构造（golden 钉不受扰），
   convergence 整跳、props.maxPoints 显式覆盖优先）。 */
export function plotCardOption(props, theme) {
  const raw = props.series || [];
  let cap;
  if (props.maxPoints != null) cap = Math.floor(+props.maxPoints);
  else cap = props.mode === "convergence" ? Infinity : getDefaultMaxPoints();
  const series = Number.isFinite(cap) ? downsamplePlotSeries(raw, cap) : raw;
  return buildEChartOption(series, props, theme);
}

/* PlotCard：图表卡片壳（工具条 CSV/PNG/SVG 导出 + 图表容器）。
   props={series, xlabel, ylabel, y2?, markline, band, xvalue, zoom, height,
          title?, mode?:"line"|"convergence", crosshair?, exportCsv?, exportPng?,
          exportName?, maxPoints?, ariaLabel?}；
   ctx={light:boolean, palette:string[]}（app.js 按 body.light 现取注入）。
   返回 echarts 实例（失败返 null 并把错误写进容器——不静默吞错，#135）。

   A6 P1-3（review_aurora_next 审查，2026-10-13）图表生命周期：T.plotCard 共
   12 个调用点，非 cached 的 10 点在页面重入/交互中重复渲染（sparams 模式
   切换/dashboard 组件增删/playground 滑条每 250ms 防抖一次等）。旧实现每次
   echarts.init 新实例 + 新 window resize 监听且从不释放——被弃实例经 resize
   闭包被 window 强引用 → detached chartDiv+canvas+zrender 全树不可回收
   （拖一轮滑条即数十实例）。本壳内建同容器守卫：调用时同容器已有存活实例
   → 先 dispose 旧实例+摘除其 resize 监听再重建（每容器至多一个存活实例+
   一个监听）。
   ═══ UI-R5 调用面归一 ═══ 同容器且实例存活 → **复用路径**：仅 setOption
   （plotCardOption 单源构造，notMerge 整体替换）刷新数据 + aria 同步——
   实例恒 1、resize 监听恒 1、导出钮装配一次（handlers 读 shell 记录现取，
   props 换代后闭包不陈旧，无需重绑）。旧 pages/charts.js plotCardCached
   包装的职责由此整体承接（其本身降级薄委托，W2-B 接口诉求闭合）。 */
const _plotShells = new WeakMap(); // 容器 el → { chart, onResize, props, ctx }

/* 主题联动遍历面：WeakRef<容器 el> 集（不阻止离场容器回收；刷新时惰性
   清理）。_trackShellRef 由 plotCard 首渲染与 registerPlotCardShell 调用。 */
const _shellRefs = new Set();

function _trackShellRef(el) {
  if (typeof WeakRef !== "function" || !el) return;
  for (const ref of _shellRefs) if (ref.deref && ref.deref() === el) return;
  _shellRefs.add(new WeakRef(el));
}

/* 壳登记/读取（charts.js 主题联动消费：refreshThemeCharts 经
   plotCardShellEntries 遍历存活壳重放 option；node 行为钉经 register 直注
   假壳驱动，不经 DOM 路径）。 */
export function registerPlotCardShell(el, shell) {
  _plotShells.set(el, shell);
  _trackShellRef(el);
  return shell;
}
export function plotCardShell(el) {
  return _plotShells.get(el) || null;
}

/* 存活壳枚举（{el, shell} 数组；失效引用惰性剔除）。 */
export function plotCardShellEntries() {
  const out = [];
  for (const ref of [..._shellRefs]) {
    const el = ref.deref && ref.deref();
    if (!el) { _shellRefs.delete(ref); continue; }
    const shell = _plotShells.get(el);
    if (shell) out.push({ el, shell });
  }
  return out;
}

/* 图像语义 aria-label（首渲染与复用路径同构单源）。 */
function _ariaLabel(props) {
  return props.ariaLabel ||
    `图表：${(props.series || []).map((s) => s.name).filter(Boolean).join("、") || "数据系列"}` +
    `${props.ylabel ? "，纵轴 " + props.ylabel : ""}${props.xlabel ? "，横轴 " + props.xlabel : ""}`;
}

export function plotCard(el, props = {}, ctx = {}) {
  try {
    const light = !!ctx.light;
    const shell = { chart: null, onResize: null, props, ctx: { light, palette: ctx.palette || [] } };
    const prevShell = _plotShells.get(el);
    if (prevShell && !prevShell.chart.isDisposed() &&
        prevShell.chart.getDom() && el.contains(prevShell.chart.getDom())) {
      // UI-R5 复用路径：仅 setOption 整体替换（新实例/新监听/新钮全为零）+
      // aria 与 shell 记录随数据刷新（主题联动重放也消费该记录）
      prevShell.props = props;
      prevShell.ctx = shell.ctx;
      prevShell.chart.setOption(plotCardOption(props, shell.ctx), true);
      prevShell.chart.getDom().setAttribute("aria-label", _ariaLabel(props));
      return prevShell.chart;
    }
    if (prevShell) { // 同容器重建：旧实例先释放+旧监听先摘除（防泄漏累积）
      if (!prevShell.chart.isDisposed()) prevShell.chart.dispose();
      window.removeEventListener("resize", prevShell.onResize);
      _plotShells.delete(el);
    }
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
    // UI-R5 导出统一出口（chart_export.js）：CSV 按开关、PNG 按开关、
    // SVG 缺省启用；handlers 读 shell 现取——复用换代后导出永是最新数据；
    // CSV 导出全分辨率原数据（降采样只在 option 层，数据诚实面）。
    const kinds = [
      ...(props.exportCsv !== false ? ["csv"] : []),
      ...(props.exportPng !== false ? ["png", "svg"] : []),
    ];
    for (const b of mkExportButtons({
      base: () => shell.props.exportName || "plotcard",
      getChart: () => shell.chart,
      getCsv: () => "\ufeff" + toCsv(shell.props.series),
    }, kinds)) tools.appendChild(b);
    const chartDiv = document.createElement("div");
    chartDiv.className = "plotcard-chart";
    // PR-1 a11y：图表容器图像语义（与 app.js drawEChart 同构）
    chartDiv.setAttribute("role", "img");
    chartDiv.setAttribute("aria-label", _ariaLabel(props));
    chartDiv.style.height = props.height || "280px";
    el.appendChild(tools);
    el.appendChild(chartDiv);
    const chart = window.echarts.init(chartDiv);
    const onResize = () => { // 监听持存活守卫：实例被 dispose 后自动跳过
      if (!chart.isDisposed()) chart.resize();
    };
    chart.setOption(plotCardOption(props, shell.ctx));
    window.addEventListener("resize", onResize);
    shell.chart = chart;
    _plotShells.set(el, shell);
    _trackShellRef(el); // UI-R5：主题联动遍历面登记
    return chart;
  } catch (e) {
    // 图表故障可见化——不静默吞错（排查 #135 教训）
    el.innerHTML = `<span style="color:var(--err)">plotcard error: ${esc(e.message)}</span>`;
    return null;
  }
}
