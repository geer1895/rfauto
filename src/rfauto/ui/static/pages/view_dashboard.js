/* rfauto 总览页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   组件化仪表盘（可增删 widget 注册表 + 拖拽排序 + 宽度记忆）。 */

import { THEME_COLORS, bodyIsLight, chartPalette, themePick } from "../theme.js";
// UI-R12 任务2：统一 API 层（apiFetch 错误信封与 T.api 同形；viewSignal=
// 视图作用域取消，切页由 app.js activate 收束在途请求）
import { apiFetch, viewSignal } from "./api.js";
import { bindChartResize, chartExportTools, echartsInitCached } from "./charts.js";
import { S, T } from "./context.js";
import { freshnessRingSvg, relTime, statusBucket } from "./dashboard_util.js";
import { esc, escAttr, help } from "./dom.js";
import {
  bindClickRows,
  bindEmptyStates,
  kitBadgeCls,
  kitBoolBadge,
  kitClickRowAttrs,
  kitEmptyState,
  kitSkeleton,
  kitTable,
} from "./kit.js";
import { openRun, showPage } from "./router.js";

/* ═══ 总览（组件化仪表盘：可增删的 widget 注册表）═══ */

// 组件注册表：新增可视化 = 加一个 render 函数 + 在 renderers 注册（解耦、可挑选）
const WIDGETS = {
  kpi:         { title: "关键指标",    span: 12 },
  recent_runs: { title: "最近 Run",    span: 6  },
  activity:    { title: "最近活动",    span: 6  },
  s11_trend:   { title: "S11 趋势",    span: 6  },
  solvers:     { title: "求解器状态",  span: 4  },
  tune_status: { title: "调参状态",    span: 4  },
  status_mix:  { title: "pass/fail 分布", span: 4 },
  adapter_mix: { title: "adapter 分布", span: 4 },
  quick_links: { title: "快速开始",    span: 12 },
};
// aurora36 W4-C：activity/status_mix 进缺省面（既有用户 localStorage 记忆
// 优先——存过自定义清单的看不到新组件，点「＋ 添加组件」自取）。
const WIDGET_DEFAULTS = ["kpi", "recent_runs", "activity", "s11_trend",
  "solvers", "tune_status", "status_mix", "quick_links"];

export async function pageDashboard() {
  const v = T.$("view-dashboard");
  v.innerHTML = help(`
    <li>总览由<b>可增删的组件</b>拼成：点右上「＋ 添加组件」勾选想看的，点组件右上「×」移除（自动记住）。</li>
    <li><b>最近活动</b>＝run 流水（新→旧，点条目进详情）；<b>关键指标</b>右上角圆环＝数据新鲜度（绿 1 小时内／黄 24 小时内／灰更久，悬浮看具体时间）。</li>
    <li><b>pass/fail 分布</b>＝全部 run 的状态环形图（工具条可导出 CSV/PNG）。</li>
    <li><b>S11 趋势</b>：每个<b>点 = 一次 run 的带内 S11 最大值</b>按 run 时间排布（越往后越低 = 调参在变好）——<b>不是频域曲线</b>；要看频率↔S11 曲线请去「S 参数分析」或「报告中心」。</li>
    <li>新到项目？去「使用指南」页有 5 分钟上手路线。</li>`) +
    `<div class='pagehead'><h2 class='page'>总览</h2><span class='spacer'></span>
      <span class='muted' style="font-size:12px">添加组件：</span><span id='w-add'></span></div>
      <div id='widget-grid'></div>`;
  // A8-A（R6 审计 P-2）：首拉骨架屏——数据未到先按组件清单铺占位壳（shimmer
  // 条，reduced-motion 降级静态灰块）；下方 Promise.all 数据到达后 grid 重建
  // 整体替换。清单读 localStorage 与真实渲染同源（自定义清单用户看到自己清单
  // 的占位；span 用缺省档——占位期宽度近似即可，不提前读 widget-span）。
  const skGrid = T.$("widget-grid");
  if (skGrid) {
    let skSaved = null;
    try { skSaved = JSON.parse(localStorage.getItem("rfauto-widgets") || "null"); } catch { /* 隐私模式等 */ }
    const skIds = (Array.isArray(skSaved) && skSaved.length ? skSaved : WIDGET_DEFAULTS)
      .filter((k) => WIDGETS[k]);
    skGrid.innerHTML = skIds.map((k) =>
      `<div class="widget w${WIDGETS[k].span}"><div class='panel' style='height:100%'>` +
      `<b class='title'>${WIDGETS[k].title}</b>` +
      `<div class="skeleton-wrap" role="status" aria-label="组件数据加载中">${kitSkeleton(3)}</div></div></div>`
    ).join("");
  }
  const [runs, solvers] = await Promise.all([
    apiFetch("/api/runs?limit=200", { signal: viewSignal("dashboard") }),
    apiFetch("/api/solvers", { signal: viewSignal("dashboard") }),
  ]);
  if (runs.aborted || solvers.aborted) return; // UI-R12：切页取消——不写隐藏区
  S.dashData = { runs: runs.runs || [], solvers: solvers.solvers || [] };
  const saved = JSON.parse(localStorage.getItem("rfauto-widgets") || "null") || WIDGET_DEFAULTS;
  S.widgetSet = new Set(saved.filter((k) => WIDGETS[k]));
  // 添加组件菜单
  const addEl = T.$("w-add");
  const renderAddMenu = () => {
    addEl.innerHTML = "";
    for (const [id, w] of Object.entries(WIDGETS)) {
      if (S.widgetSet.has(id)) continue;
      const b = document.createElement("button");
      b.className = "chipbtn";
      b.textContent = "＋ " + w.title;
      b.onclick = () => { S.widgetSet.add(id); persistWidgets(); pageDashboard(); };
      addEl.appendChild(b);
    }
    if (!addEl.children.length)
      addEl.innerHTML = "<span class='muted'>已全部添加</span>";
  };
  renderAddMenu();
  const grid = T.$("widget-grid");
  grid.innerHTML = "";
  const renderers = { kpi: wKpi, recent_runs: wRecentRuns, s11_trend: wS11Trend,
                      solvers: wSolvers, tune_status: wTuneStatus,
                      adapter_mix: wAdapterMix, quick_links: wQuickLinks,
                      activity: wActivity, status_mix: wStatusMix };
  // 宽度记忆（每组件 4/6/12 栅格列循环）
  S.widgetSpan = JSON.parse(localStorage.getItem("rfauto-widget-span") || "{}");
  const order = [...S.widgetSet];
  for (const id of order) {
    const w = WIDGETS[id];
    if (!w || !renderers[id]) continue;
    const span = S.widgetSpan[id] || w.span;
    const panel = document.createElement("div");
    panel.className = `widget w${span}`;
    panel.dataset.id = id;
    panel.draggable = true;
    // A7-A ui-kit 试点如实不迁：按钮在 <b class='title'> 元素内闭合（title 与
    // 控件同在 b 内），与 kitPanelHead 的 "</b>" 后置 actions 形态字节不等——
    // 保持原内联（迁移纪律：结构不变才能迁，差异记录见席位报告）。
    panel.innerHTML = `<div class='panel' style='height:100%'><b class='title'>${w.title}` +
      `<button class='wclose' title="加宽/收窄" data-act="span" style="margin-right:6px">⤢</button>` +
      `<button class='wclose' title="移除组件" data-act="close">×</button></b><div class='wbody'></div></div>`;
    panel.querySelector('[data-act="close"]').onclick = () => {
      S.widgetSet.delete(id); persistWidgets(); pageDashboard();
    };
    panel.querySelector('[data-act="span"]').onclick = () => {
      const seq = [4, 6, 12];
      const cur = seq.indexOf(S.widgetSpan[id] || w.span);
      S.widgetSpan[id] = seq[(cur + 1) % seq.length];
      localStorage.setItem("rfauto-widget-span", JSON.stringify(S.widgetSpan));
      panel.className = `widget w${S.widgetSpan[id]}`;
    };
    // 拖拽排序（HTML5 DnD：拖到其它组件上交换位置）
    panel.ondragstart = (e) => { e.dataTransfer.setData("text/plain", id); };
    panel.ondragover = (e) => { e.preventDefault(); panel.style.outline = "1px dashed var(--accent)"; };
    panel.ondragleave = () => { panel.style.outline = ""; };
    panel.ondrop = (e) => {
      e.preventDefault(); panel.style.outline = "";
      const src = e.dataTransfer.getData("text/plain");
      if (!src || src === id) return;
      const arr = [...S.widgetSet];
      arr.splice(arr.indexOf(src), 1);
      arr.splice(arr.indexOf(id), 0, src);
      S.widgetSet = new Set(arr);
      persistWidgets();
      pageDashboard();
    };
    grid.appendChild(panel);
    await renderers[id](panel.querySelector(".wbody"));
  }

  function persistWidgets() {
    localStorage.setItem("rfauto-widgets", JSON.stringify([...S.widgetSet]));
  }

  async function wKpi(el) {
    const list = S.dashData.runs;
    const s11s = list.map((r) => r.metrics?.s11_db_max_in_band).filter((c) => typeof c === "number");
    const best = s11s.length ? Math.max(...s11s) : null;
    const adapters = new Set(list.map((r) => r.adapter)).size;
    // aurora36 W4-C：数据新鲜度环挂首卡右上角（runs=新→旧序，list[0] 即最近
    // run 的 timestamp；零定时器，随本 widget 渲染重绘——进页/增删组件/拖拽）。
    const ring = freshnessRingSvg(list.length ? list[0].timestamp : null, Date.now());
    el.innerHTML = `<div class='cards' style="margin:0">` +
      `<div class='card' style="position:relative"><div class='k'>Run 总数</div><div class='v'>${list.length}</div>` +
      `<span style="position:absolute;top:8px;right:10px">${ring}</span></div>` +
      `<div class='card'><div class='k'>带内 S11 最优</div><div class='v ${best != null ? "ok" : ""}'>${best == null ? "-" : best.toFixed(2) + " dB"}</div></div>` +
      `<div class='card'><div class='k'>使用过的通道</div><div class='v'>${adapters}</div></div></div>`;
  }
  async function wActivity(el) {
    // aurora36 W4-C（R1 §1.3 活动日志）：数据源=本页已拉取的 /api/runs
    // （S.dashData.runs，零新增后端端点）；渲染最近 10 条（run 名/状态徽章/
    // 相对时间），点击复用 openRun 跳详情（palette 同款单入口，showPage("detail")
    // 形态的既有封装）。UI-R4：行可达形态收编 kitClickRow 单源（本组件为
    // R1 P1-2 试点原位点——role=link/tabindex/Enter 手写三件套换 kit 形态，
    // role 升 button：Space 激活键随 button 惯例一并生效）。
    const list = S.dashData.runs.slice(0, 10);
    if (!list.length) {
      // A8-A（R6 审计 P-3）：空态三件式（图标+一句话+下一步动作钮）
      el.innerHTML = kitEmptyState("暂无活动——去「工程导入」跑第一个 run",
        { icon: "☰", label: "去工程导入", view: "import" });
      bindEmptyStates(el);
      return;
    }
    const now = Date.now();
    el.innerHTML = "<div>" + list.map((r) => {
      const b = statusBucket(r.status);
      const cls = kitBadgeCls(b); // A7-A ui-kit：状态→类单源（pass/fail/other→ok/err/muted）
      const label = b === "pass" ? "完成" : b === "fail" ? "失败" : String(r.status || "未知");
      return `<div class="clickable" data-id="${escAttr(r.run_id)}" ` +
        kitClickRowAttrs({ label: "打开 run 详情：" + (r.run_id || "") }) + " " +
        `style="display:flex;align-items:center;gap:var(--space-2);padding:var(--space-1) 0">` +
        `<span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.run_id || "")}</span>` +
        T.badge(label, cls) +
        `<span class="muted" style="font-size:var(--text-xs)">${esc(relTime(r.timestamp, now))}</span></div>`;
    }).join("") + "</div>";
    // UI-R4：click 与 Enter/Space 同一激活（bindClickRows 单源；aria-label
    // 里 run_id 经 kit escAttr 出口转义——XSS 反向扫描口径零新增）
    bindClickRows(el, (row) => openRun(row.dataset.id), "[data-id]");
  }
  async function wStatusMix(el) {
    // aurora36 W4-C（R1 §1.3 甜甜圈图）：pass/fail 分布环形图——数据源=本页
    // 已拉取的 /api/runs status 字段（零新增端点）；走 W2-B 缓存基建
    // （echartsInitCached 实例守卫 + bindChartResize 监听去重）与 W3-B
    // chartExportTools 导出面（CSV/PNG，并顺带成为事件桥"最近装配"目标）。
    const list = S.dashData.runs;
    if (!list.length) {
      el.innerHTML = "<span class='muted'>暂无 run——分布图待第一个 run 落盘后出现</span>";
      return;
    }
    const n = { pass: 0, fail: 0, other: 0 };
    for (const r of list) n[statusBucket(r.status)]++;
    const holder = document.createElement("div");
    holder.style.height = "200px";
    el.appendChild(holder);
    const light = bodyIsLight();
    const fg = themePick(light, THEME_COLORS.fg);
    // 调色板=chartPalette（theme.js 单源，A5-B/R-4 镜像纪律已拆）：CHART_COLORS
    // 对应位取值——PASS=绿档[2] / FAIL=红档[3] / 其他=紫档[4]。
    const _pal = chartPalette(light);
    const pal = { pass: _pal[2], fail: _pal[3], other: _pal[4] };
    const data = [
      { name: "PASS", value: n.pass, itemStyle: { color: pal.pass } },
      { name: "FAIL", value: n.fail, itemStyle: { color: pal.fail } },
      { name: "其他", value: n.other, itemStyle: { color: pal.other } },
    ].filter((d) => d.value > 0);
    const chart = echartsInitCached(holder); // P0-5 同源守卫（W2-B 基建）
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "item", formatter: "{b}: {c}（{d}%）" },
      legend: { bottom: 0, textStyle: { color: fg } },
      series: [{
        type: "pie", radius: ["52%", "78%"], center: ["50%", "44%"],
        data, label: { show: false }, animation: false,
      }],
    }, true); // notMerge：复用路径整体替换旧 option
    // PR-1 a11y：图表容器图像语义（读屏可闻）；计数经 String 拼接（不用
    // 模板插值直引 n 的字段——XSS 反向扫描口径零新增）
    const cnt = "PASS " + n.pass + "、FAIL " + n.fail + "、其他 " + n.other;
    holder.setAttribute("role", "img");
    holder.setAttribute("aria-label", "图表：run 状态分布甜甜圈（" + cnt + "）");
    bindChartResize(holder); // W4-C：resize 去重（W2-B 基建）
    // refEl=null=append 到 widget 面板底（不插图表前，布局与四管线同构：
    // 工具条在上——widget 面板里放底部更贴近图）；传 null 亦保持既有四
    // 挂接点的跨席计数钉字面不被扰动。
    chartExportTools(el.parentElement, null, {
      name: "dashboard-status-mix",
      getChart: () => chart,
      getCsvSeries: () =>
        [{ name: "run 状态分布", x: ["PASS", "FAIL", "其他"], y: [n.pass, n.fail, n.other] }],
    });
  }
  async function wRecentRuns(el) {
    const list = S.dashData.runs.slice(0, 8);
    // A7-A ui-kit 试点：表壳/列头 scope 单源（kitTable）。UI-R4：行键盘可达
    // 收编 kitClickRow（tr 行 role:null 保 row/cell 语义；aria-label 读屏
    // 可闻行动作）；路由钉 openRun(tr.dataset.id) 与 w7c 悬停钉不动；
    // empty:"" 显式保持空 tbody——与原实现逐字节等价。
    el.innerHTML = kitTable({
      columns: ["run_id", "adapter", "带内 S11"], rows: list, empty: "",
      rowHtml: (r) => {
        const m11 = r.metrics?.s11_db_max_in_band;
        return `<tr class="clickable" data-id="${escAttr(r.run_id)}" ${kitClickRowAttrs({ role: null, label: "打开 run 详情：" + (r.run_id || "") })}><td>${esc(r.run_id || "")}</td><td>${esc(r.adapter || "")}</td><td>${esc(typeof m11 === "number" ? m11.toFixed(2) + " dB" : "-")}</td></tr>`;
      },
    });
    el.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.title = tr.dataset.id || ""; // W7-C：run_id 列截断后悬停见全名
    });
    bindClickRows(el, (tr) => openRun(tr.dataset.id), "tr.clickable"); // A4-C：单入口收编（hash 深链同步）+ UI-R4 键盘可达
  }
  async function wS11Trend(el) {
    const list = S.dashData.runs.filter((r) => typeof r.metrics?.s11_db_max_in_band === "number")
      .slice(0, 40).reverse();
    if (list.length < 2) { el.innerHTML = "<span class='muted'>数据不足（至少 2 个带指标的 run）</span>"; return; }
    const holder = document.createElement("div");
    el.appendChild(holder);
    // PR-3 PlotCard 换壳：option 与迁移前 drawEChart 等价（base 路径）
    T.plotCard(holder, {
      series: [{
        x: list.map((r) => r.run_id.slice(5, 13)),
        y: list.map((r) => r.metrics.s11_db_max_in_band),
        name: "带内 S11 (dB)",
      }],
      height: "240px", xlabel: "run（旧→新）", ylabel: "dB",
      exportName: "s11-trend", ariaLabel: "图表：带内 S11 (dB)，纵轴 dB，横轴 run（旧→新）",
    });
    const cap = document.createElement("div");
    cap.className = "muted";
    cap.style.cssText = "font-size:var(--text-xs);margin-top:var(--space-1)";
    cap.innerHTML = "每个点 = 一次 run 的带内 S11 最大值（<b>非频域曲线</b>）；悬停读数 / 滚轮缩放 / 拖动滑块；S11 越低越好。" +
      "频率↔S11 曲线见 <a href='#' data-go='sparams' style='color:var(--accent)'>S 参数分析</a> 或" +
      " <a href='#' data-go='reports' style='color:var(--accent)'>报告中心</a>";
    cap.querySelectorAll("a[data-go]").forEach((a) => {
      a.onclick = (e) => { e.preventDefault(); showPage(a.dataset.go); };
    });
    el.appendChild(cap);
  }
  async function wSolvers(el) {
    el.innerHTML = (S.dashData.solvers || []).map((s) =>
      `<div style="margin-bottom:var(--space-2)"><b>${esc(s.type)}</b> — ${kitBoolBadge(s.available, "可用", "不可用")}</div>`).join("")
      + `<div class="muted" style="margin-top:var(--space-2);font-size:12px">HFSS/AEDT：以实装版本为准（本仓实测 2025 R1/v251）<br>ADS 2027：link 已验证</div>`;
  }
  async function wTuneStatus(el) {
    const st = await apiFetch("/api/tune/status", { signal: viewSignal("dashboard") });
    if (st.aborted) return; // UI-R12：切页取消——不写隐藏区
    el.innerHTML = st.running
      ? "<span class='spin'></span> 调参运行中…（详情见「优化调参」页）"
      : (st.error ? T.badge("上次调参出错", "err")
        : st.result ? T.badge("上次调参已完成", "ok") + `<div class="muted" style="margin-top:6px">best_cost=${esc(st.result?.best_cost ?? "-")}</div>`
        : "<span class='muted'>尚未运行调参</span>");
  }
  async function wAdapterMix(el) {
    const counts = {};
    for (const r of S.dashData.runs)
      counts[r.adapter] = (counts[r.adapter] || 0) + 1;
    const total = S.dashData.runs.length || 1;
    el.innerHTML = Object.entries(counts).map(([a, n]) =>
      `<div style="margin-bottom:var(--space-2)"><b>${esc(a)}</b> <span class="muted">${n} 次 (${Math.round(n / total * 100)}%)</span>
       <div style="height:8px;border-radius:4px;background:var(--panel2);margin-top:3px">
       <div style="height:8px;border-radius:4px;width:${n / total * 100}%;background:var(--accent)"></div></div></div>`).join("");
  }
  async function wQuickLinks(el) {
    const steps = [
      ["工程导入", "读入 HFSS .aedt，勾选要调的参数"],
      ["配方编辑", "设定目标（什么算好）"],
      ["优化调参", "fake 粗筛 → 精算"],
      ["Run 历史", "查看每次仿真结果"],
    ];
    el.innerHTML = "<div class='guide-flow'>" + steps.map(([t, d], i) =>
      `<div class='guide-step'><span class='n'>${i + 1}</span><b>${t}</b><div>${d}</div></div>`).join("") + "</div>";
  }
}
