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
     `视图_指标_时间戳`），本文件私有 downloadFile 删除。
   ═══ aurora_j W1-S1 增量（双引擎叠加图异栅根治：line 族值轴支持）═══
   - opts.xvalue 值轴下 line 族（及 band 两条 stack 线）带等长 x →
     [x,y] 对数据——每条迹线自持横轴网（双引擎可信度对照 hfss/openems
     频网点数/间距可不同，category 轴按索引共享 series[0].x 会把第二
     引擎按索引拉伸错位）；散点 data=[[x,y]] 先例同构。门不满足/convergence
     组合的路径逐字节现状（golden 钉）；plotCardOption 接缝 xvalue 整跳
     分组降采样（值轴异栅下共享索引集抽稀语义不适用）。
   ═══ aurora_j W3-S9 增量（echarts 数据表文本替代：a11y W5-S23 建议④）═══
   - buildDataTable(series)：表格组装纯函数（wide/long 两态与 toCsv 同构
     ——wide=共享 x 网按索引对齐 行×列=[x, 系列...]；long=散点 [[x,y]] 或
     异栅 x 网 → [series,x,y] 长表，各系列 x 逐点保留不失真；band 是合成
     阴影带不是数据不进表）。toCsv 改为消费本函数（宽/长分派单源——
     数据表与 CSV 导出永一致），引号转义与 \r\n 行尾字节不变（行为钉）。
   - plotCard 工具条"数据表"切换钮（导出钮旁，kit 按钮同款类名）：点击在
     图表下方渲染可折叠 <table>（esc/escAttr 全动态值转义；table 带
     aria-label；默认收起零视觉回归）——读屏/复制数据的文本替代面。
     复用路径数据换代时若表展开则原样重渲染（toggle 状态保持）。 */
import { esc, escAttr } from "./pages/dom.js"; // UI-R2：esc 单源直连（拆分前自 pages.js，与入口循环引用消除）
import { t } from "./pages/i18n.js"; // W3-S9：数据表钮/caption/空态文案（词表单源，零硬编码 CJK——i18n 棘轮）
import { mkExportButtons } from "./chart_export.js"; // UI-R5：导出统一出口（CSV/PNG/SVG+时间戳命名）
import { CHART_GRID } from "./theme.js"; // W3-S12（P-5）：grid 常量单源（值冻结，golden 不受扰）

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
    grid: { ...CHART_GRID }, // W3-S12：常量单源（theme.js，值冻结=52/20/34/44 逐键同值）
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
        // aurora_j W1-S1：值轴下带线与同图 line 族同门出 [x,·] 对——否则
        // 均值线落真 x 而带线落 0..n-1 索引，带与线错位（playground explore
        // 的 line+band+xvalue 同款组合实证）。两 stack 线共用同一 s.x，
        // 堆叠按 x 对齐语义不变（第二条仍喂 upper−lower 差值）。
        const xy = opts.xvalue && opts.mode !== "convergence" &&
            Array.isArray(s.x) && Array.isArray(s.lower) &&
            Array.isArray(s.upper) && s.x.length === s.lower.length &&
            s.x.length === s.upper.length
          ? (arr) => s.x.map((v, i) => [v, arr[i]])
          : null;
        return [
          { type: "line", stack: stackId, data: xy ? xy(s.lower) : s.lower,
            showSymbol: false, silent: true,
            lineStyle: { opacity: 0 }, emphasis: { disabled: true },
            tooltip: { show: false } },
          { name: s.name, type: "line", stack: stackId,
            data: xy
              ? s.x.map((v, i) => [v, +s.upper[i] - +(s.lower?.[i] ?? 0)])
              : (s.upper || []).map((u, i) => +u - +(s.lower?.[i] ?? 0)),
            showSymbol: false, silent: true,
            lineStyle: { opacity: 0 }, emphasis: { disabled: true },
            areaStyle: { color: s.color || "#4fc3f7", opacity: 0.18 },
            tooltip: { show: false } },
        ];
      }
      // aurora_j W1-S1（异栅根治）：xvalue 值轴下 line 族带等长 x → [x,y]
      // 对数据（每条迹线自持横轴网；散点 data=[[x,y]] 先例同构）。不满足
      // 条件的路径逐字节现状（golden 钉）；convergence+xvalue 组合不支持
      // （阶梯线按 trial 序索引，view_timeline 声明组合维持原状）。
      const xyPairs = opts.xvalue && opts.mode !== "convergence" &&
        Array.isArray(s.y) && Array.isArray(s.x) && s.x.length === s.y.length
        ? s.x.map((v, i) => [v, s.y[i]])
        : null;
      return [{
        name: s.name, type: "line", data: xyPairs ? xyPairs : s.y,
        showSymbol: false,
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

/* 数据表组装（纯函数，W3-S9）：图表数据的表格形态单源——
   线族（共享同一 x 网）→ 宽表 {headers:["x", 系列...], rows:[[x, 系列...]...]}
   （行=共享索引对齐）；散点（data=[[x,y],...]）或 x 网不齐（异栅，如
   xvalue 双引擎频网）→ 长表 {headers:["series","x","y"], rows}（各系列
   x 逐点保留，不失真）。band 是合成的阴影带不是数据，不进表。
   零新计算：结构直读 series（与渲染 option 同一数据面）。toCsv 与
   plotCard 数据表面（工具条"数据表"钮）共同消费本函数——表格与 CSV
   导出永一致。 */
export function buildDataTable(series) {
  const ss = (series || []).filter((s) => s.type !== "band");
  if (!ss.length) return { headers: [], rows: [] };
  const isXY = (s) => Array.isArray(s.data) && s.data.length > 0 && Array.isArray(s.data[0]);
  const sameX = (a, b) => Array.isArray(a) && Array.isArray(b) &&
    a.length === b.length && a.every((v, i) => v === b[i]);
  if (ss.every((s) => !isXY(s))) {
    const x0 = ss[0].x || ss[0].y.map((_, i) => i);
    if (ss.slice(1).every((s) => sameX(s.x || s.y.map((_, i) => i), x0))) {
      return {
        headers: ["x", ...ss.map((s) => s.name || "y")],
        rows: x0.map((x, i) => [x, ...ss.map((s) => (s.y || [])[i] ?? "")]),
      };
    }
  }
  const rows = [];
  for (const s of ss) {
    if (isXY(s)) {
      for (const [x, y] of s.data) rows.push([s.name || "y", x, y]);
    } else {
      const xs = s.x || (s.y || []).map((_, i) => i);
      (s.y || []).forEach((y, i) => rows.push([s.name || "y", xs[i], y]));
    }
  }
  return { headers: ["series", "x", "y"], rows };
}

/* CSV 平铺（纯函数）：buildDataTable 产物 → CSV 字符串（五字符外引号
   转义 + \r\n 行尾；BOM 头由调用方加）。W3-S9 起消费 buildDataTable
   （宽/长分派单源——数据表与导出永一致）；分派逻辑与字节形态同先前
   内联实现逐字节等价（行为钉 test_to_csv_wide_long_and_quoting）。 */
export function toCsv(series) {
  const { headers, rows } = buildDataTable(series);
  if (!headers.length) return "";
  const q = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [headers, ...rows].map((r) => r.map(q).join(",")).join("\r\n");
}

/* ═══ aurora_d UI-R5：万点级曲线降采样（保形）═════════════════════════
   S 参数宽扫/多迹线可达数万频点——echarts 全量入 option 渲染与悬停读数
   随点数线性劣化。三件套：
   - minmaxIndices(ys, target)：min-max 包络抽稀（等间隔桶，每桶取 argmin+
     argmax，首末点恒保留）——**降采样前后峰值/谷值位置与数值逐位不变**：
     任何局部极值必是所在桶的桶极值，桶极值全数入选。这是保形默认档
     （Grafana/M3 同款选型）；高 Q 窄谷（宽于 1 样本、窄于桶宽）恰是 S 参数
     最关心的特征，感知类算法（LTTB）按三角形面积选点会整桶错过次深谷
     （实测 20001 点三谷曲线 LTTB 把 −25/−31dB 谷抹平成 −3dB 级，见
     runs/aurora_d/uir5/ 证据），故不做默认。
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
   convergence 整跳、props.maxPoints 显式覆盖优先；aurora_j W1-S1：xvalue
   值轴（异栅叠加）整跳降采样（语义见上方增量头注）。
   ═══ aurora_e W3-S12（R6 审计 P-5）：props.option 逃生舱（gated 纯增量）═══
   props.option 非空 → 调用方自带完整 option 直通，跳过 base 单源构造与
   降采样（非笛卡尔管线——polar/Smith/custom/heatmap 不在 builder 能力面——
   由此接入 plotCard 壳，获得 CSV/PNG/SVG 导出+同容器复用+主题联动）：
   - 对象形态：原样直通（调用方自管主题）；
   - 函数形态 (ctx) => option：渲染/复用/主题重放三条路径各现取一次
     （ctx={light, palette}——refreshThemeCharts 换档重放时函数收到新档）。
   不传 option 的调用路径此后逐字节不变（本函数其余分支不动，金钉保形）。 */
export function plotCardOption(props, theme) {
  if (props && props.option != null)
    return typeof props.option === "function" ? props.option(theme) : props.option;
  const raw = props.series || [];
  let cap;
  if (props.maxPoints != null) cap = Math.floor(+props.maxPoints);
  // aurora_j W1-S1：xvalue 值轴（异栅叠加图）整跳分组降采样——值轴下各迹线
  // 自持 [x,y] 网，"共享索引集分组抽稀"语义不适用；cred 曲线 201/401 点量级
  // 无需降采样（显式 props.maxPoints 仍最高优先，逐调用可强制抽稀）。
  else if (props.xvalue) cap = Infinity;
  else cap = props.mode === "convergence" ? Infinity : getDefaultMaxPoints();
  const series = Number.isFinite(cap) ? downsamplePlotSeries(raw, cap) : raw;
  return buildEChartOption(series, props, theme);
}

/* PlotCard：图表卡片壳（工具条 CSV/PNG/SVG 导出 + 图表容器）。
   props={series, xlabel, ylabel, y2?, markline, band, xvalue, zoom, height,
          width?, title?, mode?:"line"|"convergence", crosshair?, exportCsv?, exportPng?,
          exportName?, maxPoints?, ariaLabel?, option?, connectGroup?}；
   ctx={light:boolean, palette:string[]}（app.js 按 body.light 现取注入）。
   W3-S12（P-5）：option? 为逃生舱（语义见 plotCardOption 头注——非笛卡尔
   管线自携 option 直通，series 仅作 CSV 数据面）；width? 设图表容器宽
   （Smith 方图等比管线用；不传="" 与既有 DOM 逐字节同）。
   W5-S17（aurora_f，R1 §面3 联动 watch 激活）：connectGroup? 非空 → 实例
   挂 .group + echarts.connect(group)（同组 tooltip/axisPointer/dataZoom
   双向同步，echarts 原生零新依赖；典型面=sparams 多文件卡+叠加卡按频段
   对照）。实现面 _applyConnectGroup（首绘与复用换代两组路径共用），窗口
   缺席（node 行为钉环境）零抛跳过（#105 best-effort——联动面不阻渲染）。
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

/* W3-S9：数据表渲染（plotCard 工具条"数据表"切换钮消费）。展开时按传入
   series 现渲染（点击现取 shell.props.series——复用换代后闭包不陈旧，与
   导出钮同口径）。全动态值经 esc/escAttr（系列名/坐标=外部数据面；i18n
   词表值同为可信 chrome 也统一走转义，sink 语境不留例外）；table 带
   aria-label（读屏面）。零行数上限：与 CSV 导出同一保真口径（不静默
   截断失真；S 参数宽扫 2 万行=显式用户动作的一次性渲染成本）。 */
function _renderDataTable(wrap, series) {
  const { headers, rows } = buildDataTable(series);
  if (!headers.length) {
    wrap.innerHTML = `<span class="muted">${esc(t("common.data_table_empty"))}</span>`;
    return;
  }
  const head = headers.map((h) => `<th scope="col">${esc(h)}</th>`).join("");
  const body = rows.map((r) =>
    `<tr>${r.map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("");
  wrap.innerHTML =
    `<table aria-label="${escAttr(t("common.data_table_caption"))}">` +
    `<thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

/* W5-S17（R1 §面3 联动 watch 激活）：跨图联动组挂接（首绘与复用换代共用
   单源）。echarts.connect(group) 只把组标记为已连接（5.6 vendored 实测
   fm[group]=true），实例经 .group 加入/离场（dispose 自动移出注册表），
   重复调用幂等——首绘逐卡 connect 与复用换代重连均安全。返回是否实际
   挂接（node 行为钉消费）；window/echarts 缺席（node 假环境）零抛跳过。 */
export function applyConnectGroup(chart, group) {
  if (!chart || !group) return false;
  try {
    if (typeof window === "undefined" || !window.echarts ||
        typeof window.echarts.connect !== "function") return false;
    chart.group = group;
    window.echarts.connect(group);
    return true;
  } catch { return false; } // 联动面故障不阻渲染主路径（#105 best-effort）
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
      const prevGroup = prevShell.props ? prevShell.props.connectGroup : null;
      prevShell.props = props;
      prevShell.ctx = shell.ctx;
      prevShell.chart.setOption(plotCardOption(props, shell.ctx), true);
      prevShell.chart.getDom().setAttribute("aria-label", _ariaLabel(props));
      // W5-S17：换代换组时重挂联动（同组幂等；未传组零动作——旧行为不变）
      if (props.connectGroup && props.connectGroup !== prevGroup)
        applyConnectGroup(prevShell.chart, props.connectGroup);
      // W4-S17：复用换代=一次"最近渲染"（桥目标随最后一次渲染走；工具条
      // DOM 原地保留，钮仍存活——登记刷新零新增 DOM 面）
      const rp = el.querySelector && el.querySelector('button[data-export-kind="png"]');
      if (rp) registerRecentChartExport(rp);
      // W3-S9：数据换代时若数据表展开 → 原样重渲染（toggle 开合态保持，
      // 表内数据永与图同代；收起态零动作零渲染）
      if (prevShell.dtWrap && !prevShell.dtWrap.hidden)
        _renderDataTable(prevShell.dtWrap, props.series);
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
    // W3-S9：数据表文本替代切换钮（CSV 导出旁，kit 按钮同款类名；读屏/
    // 复制数据的文本替代面，W5-S23 a11y 建议④）。默认收起（零视觉回归）；
    // 点击现取 shell.props.series 渲染/收起（复用换代后闭包不陈旧）；
    // aria-expanded 同步开合态。node 行为钉环境无 document——整段只在
    // 浏览器路径触达（plotCard 本身不进 node 行为钉）。
    const dtBtn = document.createElement("button");
    dtBtn.type = "button";
    dtBtn.className = "minor plotcard-btn";
    dtBtn.textContent = t("common.data_table");
    dtBtn.title = t("common.data_table_title");
    dtBtn.setAttribute("aria-expanded", "false");
    const dtWrap = document.createElement("div");
    dtWrap.className = "plotcard-dtable";
    dtWrap.hidden = true;
    dtBtn.onclick = () => {
      const show = dtWrap.hidden;
      dtWrap.hidden = !show;
      dtBtn.setAttribute("aria-expanded", String(show));
      if (show) _renderDataTable(dtWrap, shell.props.series);
    };
    tools.appendChild(dtBtn);
    shell.dtBtn = dtBtn;
    shell.dtWrap = dtWrap;
    // W4-S17（aurora_e，W3-S12 建议①登记面收窄）：本壳 PNG 导出钮登记为
    // 全站"最近渲染"（palette act-export-chart 事件桥消费面）。querySelector
    // 守卫=node 行为钉假元素环境静默跳过（#105 best-effort）。
    const pngBtn = tools.querySelector
      ? tools.querySelector('button[data-export-kind="png"]') : null;
    if (pngBtn) registerRecentChartExport(pngBtn);
    const chartDiv = document.createElement("div");
    chartDiv.className = "plotcard-chart";
    // PR-1 a11y：图表容器图像语义（与 app.js drawEChart 同构）
    chartDiv.setAttribute("role", "img");
    chartDiv.setAttribute("aria-label", _ariaLabel(props));
    chartDiv.style.height = props.height || "280px";
    chartDiv.style.width = props.width || ""; // W3-S12：Smith 方图等比（缺省=""=零变化）
    el.appendChild(tools);
    el.appendChild(chartDiv);
    el.appendChild(dtWrap); // W3-S9：数据表容器（默认 hidden，零视觉回归）
    const chart = window.echarts.init(chartDiv);
    const onResize = () => { // 监听持存活守卫：实例被 dispose 后自动跳过
      if (!chart.isDisposed()) chart.resize();
    };
    chart.setOption(plotCardOption(props, shell.ctx));
    // W5-S17：首绘挂联动组（props.connectGroup 非空时；缺席=旧行为逐字节不变）
    if (props.connectGroup) applyConnectGroup(chart, props.connectGroup);
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

/* ═══ W4-S17（aurora_e，W3-S12 建议①）：palette act-export-chart 桥登记面 ═══
   四管线（polar/Smith/custom/heatmap）W3-S12 退场 chartExportTools 后，桥的
   "最近装配"登记只剩 dashboard 甜甜圈一个消费者——登记面由此迁 plotCard 壳：
   plotCard 每次渲染（首绘装配/复用换代）都把该壳工具条 PNG 钮登记为全站
   "最近渲染"（WeakRef 弱可达语义随迁——登记不滞留工具条 DOM）；chartExportTools
   （甜甜圈）经同一登记面喂同一注册表（pages/charts.js 委托调用）。
   触发面在 pages/charts.js _bindExportChartEvent（监听装配一次，事件契约
   rfauto:export-chart 无 payload 不变）：解引用→按钮已随页换血离场
   （document.contains=false，node 无 document 同口径）→ 解除登记，与导出
   出口的 isDisposed 静默守卫同口径（#105 best-effort，node 行为钉可测）。 */
let _recentPngRef = null;

/* 登记/刷新"最近渲染"目标（WeakRef 不可用的环境降级为无桥目标=零动作）。 */
export function registerRecentChartExport(btn) {
  _recentPngRef = (typeof WeakRef === "function" && btn) ? new WeakRef(btn) : null;
}

/* 桥触发：解引用→在场则代点 PNG 钮（handlers 读 shell 现取=导出永最新
   数据）；离场/已清→解除登记零动作零抛。 */
export function fireRecentChartExport() {
  const b = _recentPngRef && typeof _recentPngRef.deref === "function"
    ? _recentPngRef.deref() : null;
  if (b && typeof document !== "undefined" && document.contains &&
      document.contains(b)) b.click();
  else _recentPngRef = null;
}
