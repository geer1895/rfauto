/* rfauto 工作台各页面逻辑（由 app.js 注入工具函数）。 */

const T = {}; // 工具集（initPages 注入）
const S = { currentRunId: null, chatLog: [] };

// S-2 XSS 主向量（code_audit_slice6）：marked.parse 的输出一律经 DOMPurify
// 白名单净化后才可入 innerHTML（vendor/purify.min.js，index.html 在 marked
// 之后引入）。
// D-05 硬错化（2026-10-05 W1-E）：净化器缺失（异常环境/加载顺序被破坏）或
// 净化结果非字符串 → mdSanitize 返回 null，调用方**拒绝走 innerHTML**，
// 经 renderMarkdown 单点封装降级 textContent（模板拼接语境降级 esc() 转义
// 文本，二者同保证：攻击者内容永不作为 HTML 解释）。旧"裸 <script> 剥离"
// 弱降级已删除——它挡不住 <img onerror=…>/<svg onload=…>/<iframe src=…>
// 等向量，等于净化缺失时假装安全（物理红永不静默同源原则）。
function mdSanitize(html) {
  const P = window.DOMPurify;
  if (!P || typeof P.sanitize !== "function") return null;
  const clean = P.sanitize(html);
  return typeof clean === "string" ? clean : null;
}

// D-05：净化链可用性探针（mdSanitize 同判据，供模板拼接语境先行分流——
// 不可用时走 esc() 纯文本分支而不是把 null 拼进 innerHTML）。
function mdReady() {
  const P = window.DOMPurify;
  return !!(P && typeof P.sanitize === "function");
}

// D-05：markdown 渲染单点。净化不可用/失败 → textContent 兜底（返回
// false 供调用方按需降级样式），内容只作为纯文本显示，零 HTML 注入面。
export function renderMarkdown(el, rawHtml) {
  const clean = mdSanitize(rawHtml);
  if (clean === null) {
    el.textContent = String(rawHtml);
    return false;
  }
  el.innerHTML = clean;
  return true;
}

/* AU-4 XSS 清扫批：HTML 转义单源。API/用户数据插值进 innerHTML 模板时，
   文本语境用 esc()、属性语境用 escAttr()（引号内属性值）。二者转义同一
   五字符集（& < > " '），入参先 String() 再替换——对不含特殊字符的正常
   数据逐字节不变（渲染不变铁律）；含特殊字符时只产生实体，不再能闭合
   标签/属性。属性语境统一走 escAttr 以便审计区分语境。 */
const _ESC_RE = /[&<>"']/g;
const _ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export function esc(v) {
  return String(v).replace(_ESC_RE, (c) => _ESC_MAP[c]);
}
export function escAttr(v) {
  return esc(v);
}

/* PR-1 主题三态（dark|light|system）：localStorage 键 rfauto-theme 延续
   （规格 §D-8 纠偏：持久化已有，本批升三态）。system 态用
   matchMedia(prefers-color-scheme) 跟随并监听变化（仅 system 态生效）；
   旧用户存量的 "dark"/"light" 原样保留，新用户缺省跟随系统。 */
export const THEME_KEY = "rfauto-theme";
const THEME_MODES = ["dark", "light", "system"];

/* 纯函数（node 行为钉可测）：mode → body 是否应为浅色。 */
export function themeIsLight(mode, systemPrefersLight) {
  if (mode === "light") return true;
  if (mode === "dark") return false;
  return !!systemPrefersLight; // system（含未知值兜底）
}

let _themeCtl = null; // initPages 装配 {get, set}；未初始化时 setThemeMode 兜底直改 DOM

function _sysLight() {
  return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches);
}

/* 供命令面板等外部调用的主题设置入口。 */
export function setThemeMode(mode) {
  if (!THEME_MODES.includes(mode)) return false;
  if (_themeCtl) { _themeCtl.set(mode); return true; }
  document.body.classList.toggle("light", themeIsLight(mode, _sysLight()));
  try { localStorage.setItem(THEME_KEY, mode); } catch { /* 隐私模式等，best-effort */ }
  return true;
}
export function getThemeMode() {
  return _themeCtl ? _themeCtl.get() : (localStorage.getItem(THEME_KEY) || "system");
}

export function initPages(toolkit) {
  Object.assign(T, toolkit);
  // 主题三态：读档 → 应用 → system 态跟随系统变化 → 按钮三态循环切换
  let mode = localStorage.getItem(THEME_KEY) || "system";
  if (!THEME_MODES.includes(mode)) mode = "system";
  const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;
  const apply = () => document.body.classList.toggle("light", themeIsLight(mode, mq ? mq.matches : false));
  const THEME_LABEL = {
    dark: "🌗 深色模式",
    light: "☀ 浅色模式",
    system: "🖥 跟随系统",
  };
  const btn = T.$("theme-toggle");
  const paintBtn = () => {
    if (!btn) return;
    btn.textContent = THEME_LABEL[mode];
    btn.setAttribute("aria-label", `主题：${THEME_LABEL[mode]}（点击切换 深色→浅色→跟随系统）`);
    btn.title = "点击切换主题：深色 → 浅色 → 跟随系统";
  };
  apply();
  paintBtn();
  // 仅 system 态消费系统主题变化（dark/light 显式选定时不被系统抢走）
  const onSysChange = () => { if (mode === "system") apply(); };
  if (mq) {
    if (mq.addEventListener) mq.addEventListener("change", onSysChange);
    else mq.addListener(onSysChange); // 旧 Safari 降级
  }
  _themeCtl = {
    get: () => mode,
    set: (m) => {
      if (!THEME_MODES.includes(m)) return false;
      mode = m;
      try { localStorage.setItem(THEME_KEY, m); } catch { /* best-effort */ }
      apply();
      paintBtn();
      return true;
    },
  };
  if (btn) {
    btn.onclick = () => _themeCtl.set(THEME_MODES[(THEME_MODES.indexOf(mode) + 1) % THEME_MODES.length]);
  }
}

export function showPage(v) {
  const views = {
    dashboard: pageDashboard, import: pageImport, recipe: pageRecipe,
    tune: pageTune, loopboard: pageLoopBoard, runs: pageRuns, detail: showRun,
    agent: pageAgent, guide: pageGuide, solvers: pageSolvers,
    calibration: pageCalibration, sparams: pageSparams, timeline: pageTimeline,
    reports: pageReports, tools: pageTools, playground: pagePlayground,
    farfield: pageFarfield, field: pageField, optstack: pageOptStack,
    datasets: pageDatasets, anchors: pageAnchors, uq: pageUq,
    /* PR-5/6/8（ge8b Wave B 席B2）：画廊 / 战役仪表盘 / 剖析 */
    gallery: pageGallery, campaign: pageCampaign, profile: pageProfile,
    /* PR-9 调度队列页（ge8b Wave B 席B3）：战役队列+G13 决策日志 */
    queue: pageQueue,
  };
  T.activate(v);
  (views[v] || pageDashboard)(S.currentRunId);
}

/* PR-2 命令面板入口：从任意处打开 run 详情（S.currentRunId 单源在本模块）。 */
export function openRun(runId) {
  S.currentRunId = runId;
  showPage("detail");
}

/* 本页说明组件（每页顶部可折叠帮助，降低上手门槛） */
function help(text) {
  return `<details class="help"><summary>❓ 本页说明（点开查看）</summary>${text}</details>`;
}

/* 文件浏览器（弹层）：选 .aedt/.yaml 文件或目录 */
function fileBrowser(startPath, onPick) {
  let old = document.getElementById("fs-browser");
  if (old) old.remove();
  const modal = document.createElement("div");
  modal.id = "fs-browser";
  modal.setAttribute("role", "dialog"); // PR-1 a11y：模态弹层语义
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-label", "选择文件或目录");
  modal.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:60;display:flex;align-items:center;justify-content:center";
  modal.innerHTML = `<div style="background:var(--panel);border:1px solid var(--border);border-radius:10px;width:640px;max-height:80vh;display:flex;flex-direction:column;padding:14px">
    <div class="toolbar"><b>选择文件 / 目录</b>
      <input id="fs-path" style="flex:1" placeholder="D:/rf_workspace 或其子目录">
      <button class="minor" id="fs-go">跳转</button>
      <button class="minor" id="fs-close">关闭</button></div>
    <div id="fs-list" class="muted" style="overflow:auto;flex:1;min-height:260px">加载中...</div></div>`;
  document.body.appendChild(modal);
  const close = () => modal.remove();
  modal.querySelector("#fs-close").onclick = close;
  modal.onclick = (e) => { if (e.target === modal) close(); };

  async function load(path) {
    const d = await T.api("/api/fs/list?path=" + encodeURIComponent(path || ""));
    const el = modal.querySelector("#fs-list");
    if (!d.ok) { el.textContent = d.error; return; }
    modal.querySelector("#fs-path").value = d.path;
    let html = d.parent ? `<div class="fs-row" data-p="${escAttr(d.parent)}" style="cursor:pointer">📁 ..（上级）</div>` : "";
    for (const e of d.entries) {
      const icon = e.kind === "dir" ? "📁" : (e.name.endsWith(".aedt") ? "📡" : "📄");
      html += `<div class="fs-row" data-p="${escAttr(e.path)}" data-k="${escAttr(e.kind)}" style="cursor:pointer;padding:3px 4px">${icon} ${esc(e.name)}</div>`;
    }
    el.innerHTML = html || "<span class='muted'>空目录</span>";
    el.querySelectorAll(".fs-row").forEach((row) => {
      row.onclick = () => {
        if (row.dataset.k === "dir") load(row.dataset.p);
        else { onPick(row.dataset.p); close(); }
      };
    });
  }
  modal.querySelector("#fs-go").onclick = () => load(modal.querySelector("#fs-path").value.trim());
  load(startPath);
}

/* ═══ 总览（组件化仪表盘：可增删的 widget 注册表）═══ */

// 组件注册表：新增可视化 = 加一个 render 函数 + 在 renderers 注册（解耦、可挑选）
const WIDGETS = {
  kpi:         { title: "关键指标",    span: 12 },
  recent_runs: { title: "最近 Run",    span: 6  },
  s11_trend:   { title: "S11 趋势",    span: 6  },
  solvers:     { title: "求解器状态",  span: 4  },
  tune_status: { title: "调参状态",    span: 4  },
  adapter_mix: { title: "adapter 分布", span: 4 },
  quick_links: { title: "快速开始",    span: 12 },
};
const WIDGET_DEFAULTS = ["kpi", "recent_runs", "s11_trend", "solvers", "tune_status", "quick_links"];

async function pageDashboard() {
  const v = T.$("view-dashboard");
  v.innerHTML = help(`
    <li>总览由<b>可增删的组件</b>拼成：点右上「＋ 添加组件」勾选想看的，点组件右上「×」移除（自动记住）。</li>
    <li><b>S11 趋势</b>：每个<b>点 = 一次 run 的带内 S11 最大值</b>按 run 时间排布（越往后越低 = 调参在变好）——<b>不是频域曲线</b>；要看频率↔S11 曲线请去「S 参数分析」或「报告中心」。</li>
    <li>新到项目？去「使用指南」页有 5 分钟上手路线。</li>`) +
    `<div class='pagehead'><h2 class='page'>总览</h2><span class='spacer'></span>
      <span class='muted' style="font-size:12px">添加组件：</span><span id='w-add'></span></div>
      <div id='widget-grid'></div>`;
  const [runs, solvers] = await Promise.all([T.api("/api/runs?limit=200"), T.api("/api/solvers")]);
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
                      adapter_mix: wAdapterMix, quick_links: wQuickLinks };
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
    el.innerHTML = `<div class='cards' style="margin:0">` +
      `<div class='card'><div class='k'>Run 总数</div><div class='v'>${list.length}</div></div>` +
      `<div class='card'><div class='k'>带内 S11 最优</div><div class='v ${best != null ? "ok" : ""}'>${best == null ? "-" : best.toFixed(2) + " dB"}</div></div>` +
      `<div class='card'><div class='k'>使用过的通道</div><div class='v'>${adapters}</div></div></div>`;
  }
  async function wRecentRuns(el) {
    const list = S.dashData.runs.slice(0, 8);
    el.innerHTML = `<table><thead><tr><th>run_id</th><th>adapter</th><th>带内 S11</th></tr></thead><tbody>` +
      list.map((r) => {
        const m11 = r.metrics?.s11_db_max_in_band;
        return `<tr class="clickable" data-id="${escAttr(r.run_id)}"><td>${esc(r.run_id || "")}</td><td>${esc(r.adapter || "")}</td><td>${esc(typeof m11 === "number" ? m11.toFixed(2) + " dB" : "-")}</td></tr>`;
      }).join("") + "</tbody></table>";
    el.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.onclick = () => { S.currentRunId = tr.dataset.id; showPage("detail"); };
    });
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
    cap.style.cssText = "font-size:11px;margin-top:4px";
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
      `<div style="margin-bottom:8px"><b>${esc(s.type)}</b> — ${s.available ? T.badge("可用", "ok") : T.badge("不可用", "err")}</div>`).join("")
      + `<div class="muted" style="margin-top:8px;font-size:12px">HFSS 2023.1：verified 真机通道<br>HFSS 2026.1：受 PyAEDT #7410 阻塞<br>ADS 2027：link 已验证</div>`;
  }
  async function wTuneStatus(el) {
    const st = await T.api("/api/tune/status");
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
      `<div style="margin-bottom:8px"><b>${esc(a)}</b> <span class="muted">${n} 次 (${Math.round(n / total * 100)}%)</span>
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

/* ═══ 使用指南 ═══ */
function pageGuide() {
  const v = T.$("view-guide");
  v.innerHTML = help(`
    <li>本页 = 内置说明书。第一次用？按下面 4 步走一遍 fake 演示即可上手。</li>
    <li>随时可以回「总览」点「＋ 添加组件」定制你想盯的面板。</li>`) +
    `<h2 class='page'>使用指南 <small>写给第一次接触 rfauto 的你</small></h2>
    <div class='panel'><b class='title'>rfauto 是做什么的</b>
      <p>HFSS/ADS 这类电磁仿真很慢，直接在真机上反复试参数代价很高。rfauto 的思路是：
      <b>用快速代理（fake/openEMS）先粗筛参数 → 再用 HFSS/ADS 精算少数候选</b>，
      并用 P0 门禁（排序一致性 recall≥80%）保证"粗筛挑出来的确实靠谱"。</p></div>
    <div class='panel'><b class='title'>5 分钟上手路线</b>
      <div class='guide-flow'>
        <div class='guide-step'><span class='n'>1</span><b>工程导入</b><div>读入你的 HFSS 工程（.aedt），勾选要调的变量。</div></div>
        <div class='guide-step'><span class='n'>2</span><b>配方编辑</b><div>补 objectives（什么算"好"，如带内 S11&lt;-15dB），确认优化范围。</div></div>
        <div class='guide-step'><span class='n'>3</span><b>优化调参</b><div>先用 fake adapter 跑通流程（秒级），再切 hfss 真机精算。</div></div>
        <div class='guide-step'><span class='n'>4</span><b>Run 历史</b><div>看 S 参数曲线与指标，best_params 就是推荐工作点。</div></div>
      </div></div>
    <div class='panel'><b class='title'>概念速查</b>
      <table class="glossary"><tbody>
        <tr><td>配方 (recipe)</td><td>一次仿真的完整定义：模型 + 参数 + 扫频 + 目标 + 优化设置（YAML 文件）。</td></tr>
        <tr><td>Run</td><td>配方的一次实际执行；每个 run 有 id、指标、S 参数曲线和产物存档。</td></tr>
        <tr><td>adapter</td><td>执行仿真的通道：fake（秒级解析演示）/ openEMS（免费 FDTD）/ HFSS（商业真机）。</td></tr>
        <tr><td>objectives</td><td>"什么算好"的裁判，如「带内 S11 最大值低于 -15dB」。优化器按它打分。</td></tr>
        <tr><td>多保真</td><td>fake 粗筛 + 高保真精算的两阶段流程；靠 P0 gate 保证排序一致性。</td></tr>
        <tr><td>P0 gate</td><td>可信度验收：fake 与高保真对同一批参数的排名 Spearman ρ≥0.8 且 top-5 命中≥80%。</td></tr>
        <tr><td>Agent 三层 Gate</td><td>LLM 提参数 → L1/L2 自动校验 → 生成 token → 你在收件箱批准才执行。</td></tr>
      </tbody></table></div>
    <div class='panel'><b class='title'>常见问题</b>
      <li><b>为什么第一次都建议跑 fake？</b> fake 秒级返回，先确认配方的目标/范围写得对，再上真机不浪费 license 时间。</li>
      <li><b>调参结果 plateau 在 -6dB？</b> 通常是结构级失配（线宽/端口归一化），纯几何调参到顶了——先审模型再调参。</li>
      <li><b>HFSS 2023 还是 2026？</b> 2023.1 是已验证通道；2026.1 暂受 PyAEDT 官方 issue #7410 阻塞，修复后一行配置切回。</li>
      <li><b>openEMS 第一次跑很慢？</b> 真实谐振结构要跑满能量衰减（旧参考里 280s 是坏模型的假快）。结果会缓存，同配置秒回。</li>
      </div>
    <div class='panel'><b class='title'>下一步去哪</b>
      <li>深入口径与踩坑：仓库 <span class="muted">docs/rf_template_references.md</span> 与 。</li>
      <li>想看某个页面怎么用：每个页面顶部都有「❓ 本页说明」。</li></div>`;
}

/* ═══ 工程导入（HFSS .aedt → 配方草稿）═══ */
let importSpec = null;

async function pageImport() {
  const v = T.$("view-import");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>工程文件</b>：点「浏览」选 .aedt（也可手输路径）；2023.1 为已验证通道。</li>
      <li><b>读取工程</b> 后列出设计变量：勾选哪些进优化空间、编辑 low/high（默认取 HFSS Optimetrics 扫参范围，没有则 ±20%）。</li>
      <li><b>保存配方草稿</b> 后到「配方编辑」页补目标（objectives），再进「优化调参」。</li>
      <li>依赖变量（表达式引用其它变量）与非数值变量自动排除。</li>`) +
    `<h2 class='page'>工程导入 <small>HFSS .aedt → 设计规格 → 配方草稿</small></h2>
      <div class='panel'><div class='toolbar'>
        工程文件: <input id='imp-project' style="flex:1;min-width:280px" placeholder='hfss_projects/xxx.aedt'>
        <button class='minor' id='imp-browse'>浏览…</button>
        设计名: <input id='imp-design' size='12' placeholder='留空取第一个'>
        版本: <select id='imp-version'><option>2023.1</option><option>2026.1</option></select>
        <button class='act' id='imp-read'>读取工程</button>
      </div><div id='imp-msg' class='muted'>首次启动 AEDT 需约 30 秒；读取前请确认工程未被其它 AEDT 窗口占用（残留 .lock 会导致失败）。</div></div>
      <div id='imp-spec'></div>`;
  T.$("imp-read").onclick = readProject;
  T.$("imp-browse").onclick = () =>
    fileBrowser("", (p) => { T.$("imp-project").value = p; });

  async function readProject() {
    const btn = T.$("imp-read");
    btn.disabled = true; btn.textContent = "读取中...（首次启动 AEDT 需 ~30s）";
    T.$("imp-msg").textContent = "";
    importSpec = await T.api("/api/hfss/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: T.$("imp-project").value.trim(),
                             design: T.$("imp-design").value.trim() || null,
                             version: T.$("imp-version").value }),
    });
    btn.disabled = false; btn.textContent = "读取工程";
    if (!importSpec.ok) { T.$("imp-msg").innerHTML = `<span style="color:var(--err)">${esc(importSpec.error)}</span>`; return; }
    renderSpec();
  }

  function renderSpec() {
    const s = importSpec.spec, vars = s.variables || {};
    const names = Object.keys(vars);
    const rows = names.map((n) => {
      const info = vars[n];
      const rng = (s.parametrics || {})[n];
      const val = parseFloat(info.value);
      const dis = info.dependent || isNaN(val);
      const low = rng ? rng.start : (isNaN(val) ? "" : (val * 0.8).toPrecision(4));
      const high = rng ? rng.stop : (isNaN(val) ? "" : (val * 1.2).toPrecision(4));
      const src = rng ? T.badge("扫参范围", "ok") : T.badge("±20%", "muted");
      return `<tr>
        <td><input type="checkbox" class="imp-include" data-n="${escAttr(n)}" ${dis ? "" : "checked"} ${dis ? "disabled" : ""}></td>
        <td>${esc(n)}</td><td class="muted">${esc(info.expression)}</td>
        <td><input class="imp-low" data-n="${escAttr(n)}" value="${escAttr(low)}" size="9" ${dis ? "disabled" : ""}></td>
        <td><input class="imp-high" data-n="${escAttr(n)}" value="${escAttr(high)}" size="9" ${dis ? "disabled" : ""}></td>
        <td>${rng ? esc(rng.start + " ~ " + rng.stop + " (step " + rng.step + ")") : src}</td>
      </tr>`;
    }).join("");
    T.$("imp-spec").innerHTML = `
      <div class='panel'><b class='title'>设计规格 — ${esc(s.design || "?")}（${names.length} 个变量，${Object.keys(s.parametrics || {}).length} 个已有扫参范围）</b>
      <table><thead><tr><th></th><th>变量</th><th>表达式</th><th>low</th><th>high</th><th>来源</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class='grid2'>
        <div class='panel'><b class='title'>端口 / Setup</b>
          <div>${(s.ports || []).map((p) => `${esc(p.name)} <span class="muted">${esc(p.type)}</span>`).join("<br>") || "<span class='muted'>无端口边界</span>"}</div>
          <div class="muted" style="margin-top:8px">Setup: ${esc(s.setup?.setup_name || "无")}；Sweep: ${(s.setup?.sweeps || []).map((w) => esc(w.range_start + "~" + w.range_end)).join("、") || "无"}</div>
        </div>
        <div class='panel'><b class='title'>生成配方</b>
          <div class="toolbar">目标文件: <input id='imp-out' size='30' value='recipes/custom/imported.yaml'>
          <button class='minor' id='imp-out-browse'>浏览…</button>
          <button class='act' id='imp-save'>保存配方草稿</button></div>
          <div id='imp-saved'></div>
          <div class="muted" style="margin-top:8px">保存后到「配方编辑」页加载它，补 objectives（什么算"好"）再调参。</div>
        </div>
      </div>`;
    T.$("imp-save").onclick = saveRecipeDraft;
    T.$("imp-out-browse").onclick = () =>
      fileBrowser("", (p) => {
        if (!p.endsWith(".yaml")) p = p + "/imported.yaml";
        T.$("imp-out").value = p.replace(/\\/g, "/");
      });
  }

  async function saveRecipeDraft() {
    const params = {};
    document.querySelectorAll("#imp-spec .imp-include").forEach((cb) => {
      if (!cb.checked) return;
      const n = cb.dataset.n;
      const lo = document.querySelector(`.imp-low[data-n="${n}"]`).value.trim();
      const hi = document.querySelector(`.imp-high[data-n="${n}"]`).value.trim();
      const f = (x) => parseFloat(x) || 0;
      params[n] = { value: parseFloat(importSpec.spec.variables[n].value) || 0, low: f(lo), high: f(hi) };
    });
    const outPath = T.$("imp-out").value.trim();
    const r = await T.api("/api/hfss/import", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project: importSpec.project, design: importSpec.design,
                             version: T.$("imp-version").value, out: outPath }),
    });
    if (!r.ok) return T.msg("导入失败: " + r.error, false);
    // 用客户端编辑后的 params 覆盖保存（服务端 out 只含默认范围）
    await fetch("/api/recipe", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: outPath, create: {
        ...importSpec.recipe, params,
        hfss_var_map: Object.fromEntries(Object.keys(params).map((n) => [n, n])),
      } }) });
    T.$("imp-saved").innerHTML = T.badge("已保存", "ok") + ` <span class="muted">${escAttr(outPath)}</span>`;
    T.msg("配方草稿已生成", true);
  }
}

/* ═══ 配方编辑（含配方目录 + 字段说明）═══ */
let currentRecipe = null;

async function pageRecipe() {
  const v = T.$("view-recipe");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>配方目录</b>：recipes/ 下全部配方，点选加载。每个配方 = 一次仿真的完整定义（模型+参数+目标+优化设置）。工作副本（runs/recipe_workcopy）单独分组显示并标注「工作副本」——保存对原件的改动会重定向到工作副本（原件受保护），人工审阅后经审批链（rfauto inbox）入库。</li>
      <li><b>参数表</b>：改值即时刷新 3D 预览；「优化范围」是调参时允许搜索的区间。</li>
      <li><b>保存并运行</b>：单次仿真——fake 秒级演示 / openEMS 真跑 / HFSS 真机。</li>
      <li>各字段含义见页面底部「配方要素说明」。</li>`) +
    `<h2 class='page'>配方编辑</h2>
      <div class='grid2'>
        <div class='panel'><b class='title'>配方目录（点选加载）</b><div id='recipe-cat' class='muted'>加载中...</div></div>
        <div class='panel'><div class='toolbar' style="align-items:flex-start;flex-direction:column">路径:
          <input id='recipe-path' style='width:100%' placeholder='recipes/wilkinson_pd_v1.yaml'>
          <button class='minor' id='recipe-load'>加载</button>
          <span class='muted'>模型: <span id='recipe-model'>-</span></span></div>
        </div>
      </div>
      <div class='grid2'>
        <div class='panel'><b class='title'>参数（可改值；保存后生效）</b><table id='params-table'><thead>
          <tr><th>名称</th><th>值</th><th>单位</th><th>优化范围</th></tr></thead><tbody></tbody></table>
          <p class='toolbar'><button class='act' id='recipe-save'>保存配方</button>
          <button class='act' id='recipe-run'>运行一次</button>
          <select id='run-adapter'><option value='fake'>fake（秒级演示）</option><option value='openems'>openEMS（FDTD 真跑）</option><option value='hfss'>HFSS（真机）</option></select></p></div>
        <div class='panel'><b class='title'>3D 预览（随表单值实时渲染）</b><div id='recipe-3d'></div></div>
      </div>
      <div class='grid2'>
        <div class='panel'><b class='title'>扫频 / 仿真设置 (setup) — 表单化</b>
          <div id='setup-form' class='toolbar' style='flex-wrap:wrap;gap:8px'></div>
          <details class='help' style='margin-top:8px'><summary>高级：完整 setup JSON（表单改不到的字段在这改）</summary>
          <pre id='setup-pre' contenteditable='true' spellcheck='false'></pre></details></div>
        <div class='panel'><b class='title'>优化设置 (optimization + objectives)</b>
          <div id='opt-form'></div>
          <details class='help' style='margin-top:8px'><summary>高级：objectives JSON（目标判定，表单改不到）</summary>
          <pre id='opt-pre' contenteditable='true' spellcheck='false'></pre></details></div>
      </div>
      <div class='panel'><b class='title'>配方要素说明</b><div id='recipe-help' class='muted'></div></div>`;
  T.$("recipe-load").onclick = loadRecipe;
  T.$("recipe-save").onclick = () => saveRecipe(false);
  T.$("recipe-run").onclick = () => saveRecipe(true);
  loadCatalog();

  async function loadCatalog() {
    const d = await T.api("/api/recipes");
    const el = T.$("recipe-cat");
    const orig = d.recipes || [], work = d.workcopies || [];
    const row = (r, isWorkcopy) =>
      `<div class="clickable" style="padding:5px 8px;border-radius:6px" data-p="${escAttr(r.path)}">
        <b>${esc(r.path.split("/").pop())}</b> ${isWorkcopy ? T.badge("工作副本", "warn") + " " : ""}<span class="muted">${esc(r.model)}</span><br>
        <span class="muted" style="font-size:11.5px">${esc(r.n_params ?? "?")} 参数 · ${esc(r.n_objectives ?? "?")} 目标 · 频段 ${esc(JSON.stringify(r.freq_range))}</span></div>`;
    // C22 分组：recipes/ 原件在上；工作副本（runs/recipe_workcopy）单独分组，
    // 标注「工作副本」并给人工审阅入库提示（rfauto inbox 审批链，前端只渲染）。
    el.innerHTML =
      `<div style="margin-bottom:4px"><b>原件（recipes）</b> <span class="muted" style="font-size:11.5px">${orig.length} 个</span></div>` +
      orig.map((r) => row(r, false)).join("") +
      (work.length ?
        `<div style="margin:10px 0 4px"><b>工作副本（runs/recipe_workcopy）</b> <span class="muted" style="font-size:11.5px">${work.length} 个</span></div>` +
        `<div class="muted" style="font-size:11.5px;margin:0 0 4px">人工审阅后入库：与原件 diff 确认改动 → 经审批链（<b>rfauto inbox</b> 审批收件箱，propose→approve→apply 三层 Gate）或显式写回原件后 git commit 留痕。</div>` +
        work.map((r) => row(r, true)).join("")
        : "");
    el.querySelectorAll("[data-p]").forEach((row) => {
      row.onclick = () => { T.$("recipe-path").value = row.dataset.p; loadRecipe(); };
      row.onmouseenter = () => { row.style.background = "var(--panel2)"; };
      row.onmouseleave = () => { row.style.background = ""; };
    });
    T.$("recipe-help").innerHTML = Object.entries(d.help || {}).map(([k, txt]) =>
      `<div style="margin-bottom:6px"><b style="color:var(--fg)">${esc(k)}</b> — ${esc(txt)}</div>`).join("");
  }

  async function loadRecipe() {
    const val = await T.api("/api/recipe?path=" + encodeURIComponent(T.$("recipe-path").value.trim()));
    if (!val.ok) return T.msg(val.errors.join("; "), false);
    currentRecipe = val;
    // C22：工作副本视图标注（service 端 is_workcopy/review_hint，前端只渲染）
    T.$("recipe-model").textContent =
      `${val.model}（模板: ${val.template_hint || "无"}）` + (val.is_workcopy ? " · 工作副本" : "");
    T.$("recipe-model").title = val.is_workcopy ? (val.review_hint || "") : "";
    const tb = T.$("params-table").tBodies[0];
    tb.innerHTML = "";
    for (const p of val.params) {
      const bounds = p.bounds ? `[${p.bounds.join(", ")}]`
        : (val.optimization.params[p.name] ? `[${val.optimization.params[p.name].low}, ${val.optimization.params[p.name].high}]` : "-");
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(p.name)}</td><td><input data-param="${escAttr(p.name)}" value="${escAttr(p.value ?? "")}" size="10"></td><td>${esc(p.unit || "")}</td><td class="muted">${esc(bounds)}</td>`;
      tr.querySelector("input").oninput = renderRecipe3D;
      tb.appendChild(tr);
    }
    T.$("setup-pre").textContent = JSON.stringify(val.setup, null, 2);
    T.$("opt-pre").textContent = JSON.stringify({ objectives: val.objectives, optimization: val.optimization }, null, 2);
    renderSetupForm(val.setup);
    renderOptForm(val.optimization);
    renderRecipe3D();
  }

  /* 扫参表单化：表单是主输入，写回 JSON 编辑框（保存仍以 JSON 为准，链路不变） */
  function renderSetupForm(setup) {
    const fr = Array.isArray(setup.freq_range_ghz) ? setup.freq_range_ghz : ["", ""];
    const fields = [
      ["solver", "求解器", setup.solver ?? "", "text"],
      ["f0", "扫频起 (GHz)", fr[0] ?? "", "number"],
      ["f1", "扫频止 (GHz)", fr[1] ?? "", "number"],
      ["points", "频点数", setup.points ?? "", "number"],
      ["convergence_delta", "收敛 Δ", setup.convergence_delta ?? "", "number"],
      ["radiation_box", "辐射边界", setup.radiation_box ?? "", "text"],
    ];
    const form = T.$("setup-form");
    form.innerHTML = fields.map(([k, label, v, t]) =>
      `<label>${label}: <input data-setup="${k}" type="${t}" value="${escAttr(v)}" size="9" step="any"></label>`).join("");
    form.oninput = syncSetupForm;
  }
  function syncSetupForm() {
    let s;
    try { s = JSON.parse(T.$("setup-pre").textContent) || {}; }
    catch { return; } // JSON 被手改坏了就不覆盖，保存时会报错提示
    const read = (k) => {
      const el = form.querySelector(`input[data-setup="${k}"]`);
      if (!el) return undefined;
      const raw = el.value.trim();
      if (el.type === "number") { const n = Number(raw); return raw === "" ? undefined : (isNaN(n) ? raw : n); }
      return raw === "" ? undefined : raw;
    };
    const form = T.$("setup-form");
    const assign = (obj, k, v) => { if (v !== undefined) obj[k] = v; };
    assign(s, "solver", read("solver"));
    assign(s, "radiation_box", read("radiation_box"));
    assign(s, "points", read("points"));
    assign(s, "convergence_delta", read("convergence_delta"));
    const f0 = read("f0"), f1 = read("f1");
    if (f0 !== undefined || f1 !== undefined) {
      const old = Array.isArray(s.freq_range_ghz) ? s.freq_range_ghz : [undefined, undefined];
      s.freq_range_ghz = [f0 ?? old[0], f1 ?? old[1]];
    }
    T.$("setup-pre").textContent = JSON.stringify(s, null, 2);
  }
  function renderOptForm(opt) {
    const names = Object.keys(opt.params || {});
    const form = T.$("opt-form");
    if (!names.length) { form.innerHTML = "<span class='muted'>配方未定义 optimization.params（搜索空间）</span>"; return; }
    form.innerHTML = `<table><thead><tr><th>调参变量</th><th>low</th><th>high</th></tr></thead><tbody>` +
      names.map((n) => {
        const p = opt.params[n] || {};
        return `<tr><td><b>${esc(n)}</b></td>
          <td><input class="opt-b" data-param="${escAttr(n)}" data-k="low" value="${escAttr(p.low ?? "")}" size="9" type="number" step="any"></td>
          <td><input class="opt-b" data-param="${escAttr(n)}" data-k="high" value="${escAttr(p.high ?? "")}" size="9" type="number" step="any"></td></tr>`;
      }).join("") + "</tbody></table>" +
      `<div class="muted" style="margin-top:4px;font-size:11.5px">调整搜索空间（low/high）；目标 objectives 在右侧「高级」折叠框里。</div>`;
    form.oninput = syncOptForm;
  }
  function syncOptForm() {
    let d;
    try { d = JSON.parse(T.$("opt-pre").textContent); }
    catch { return; }
    d.optimization = d.optimization || {};
    d.optimization.params = d.optimization.params || {};
    document.querySelectorAll("#opt-form input.opt-b").forEach((el) => {
      const p = d.optimization.params[el.dataset.param];
      if (!p) return;
      const n = Number(el.value);
      if (el.value.trim() !== "" && !isNaN(n)) p[el.dataset.k] = n;
    });
    T.$("opt-pre").textContent = JSON.stringify(d, null, 2);
  }

  async function renderRecipe3D() {
    if (!currentRecipe) return;
    const params = {};
    document.querySelectorAll("#params-table input[data-param]").forEach((el) => {
      params[el.dataset.param] = Number(el.value) || 0;
    });
    const r = await T.api("/api/model3d", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template: currentRecipe.template_hint, params }),
    });
    T.drawBoxes(T.$("recipe-3d"), r);
  }

  async function saveRecipe(andRun) {
    if (!currentRecipe) return T.msg("先加载配方", false);
    const updates = { params: {} };
    document.querySelectorAll("#params-table input[data-param]").forEach((el) => {
      const raw = el.value.trim();
      updates.params[el.dataset.param] = isNaN(Number(raw)) || raw === "" ? raw : Number(raw);
    });
    try { updates.setup = JSON.parse(T.$("setup-pre").textContent); }
    catch { return T.msg("setup 不是合法 JSON", false); }
    try {
      const opt = JSON.parse(T.$("opt-pre").textContent);
      updates.objectives = opt.objectives; updates.optimization = opt.optimization;
    } catch { return T.msg("optimization/objectives 不是合法 JSON", false); }
    const r = await T.api("/api/recipe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: currentRecipe.recipe_path, updates }),
    });
    if (!r.ok) return T.msg("保存被拒: " + r.errors.join("; "), false);
    // 写面守卫：recipes/ 原件受保护时 service 另存工作副本并回传实际路径，
    // 后续运行/加载一律消费该路径（原件字节不变，TODO 增量②）
    if (r.recipe_path) {
      currentRecipe.recipe_path = r.recipe_path;
      if (r.workcopy) T.$("recipe-path").value = r.recipe_path;
    }
    T.msg(r.workcopy ? (r.message || `已另存工作副本: ${r.recipe_path}`) : "配方已保存", true);
    if (andRun) {
      const run = await T.api("/api/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: currentRecipe.recipe_path, adapter: T.$("run-adapter").value }),
      });
      if (run.ok) { T.msg(`运行完成: cost=${run.cost}`, true); S.currentRunId = run.run_id; showPage("detail"); }
      else T.msg("运行失败: " + (run.errors || []).join("; "), false);
    }
  }
}

/* ═══ 优化调参 ═══ */
let tuneTimer = null;

async function pageTune() {
  const v = T.$("view-tune");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>adapter</b>：调参用的仿真通道。fake=秒级解析模型（先验证流程）；hfss=真机（慢、耗 license）；openEMS=免费 FDTD。</li>
      <li><b>trials</b>：试验次数——每 trial 仿真一次配方并按 objectives 打分，TPE 采样器会越猜越准。</li>
      <li><b>多保真</b>：先用 fake 粗筛出 Pareto 候选、再对 top-k 用高保真精算（省时数倍）。可信度看 P0 gate（recall≥80%）。</li>
      <li>结果里的 <b>best_params</b> 就是推荐工作点，可回「配方编辑」应用后真机验证。</li>
      <li>调参前确认配方的 objectives 与 optimization.params 范围已定义。</li>`) +
    `<h2 class='page'>优化调参 <small>fake 粗筛 → 高保真精算（多保真）</small></h2>
      <div class='panel'><div class='toolbar'>
        配方: <input id='tune-path' size='36' value='recipes/wilkinson_pd_v1.yaml'>
        adapter: <select id='tune-adapter'><option>fake</option><option>hfss</option><option>openems</option></select>
        trials: <input id='tune-trials' size='4' value='30'>
        sampler: <select id='tune-sampler'><option>tpe</option><option>cmaes</option></select>
        多保真: <input type='checkbox' id='tune-multi'>
        <button class='act' id='tune-go'>启动</button>
        <span id='tune-spin'></span>
      </div><div id='tune-recipe-info' class='muted' style="margin-top:6px"></div></div>
      <div class='panel' id='tune-result' style='display:none'><b class='title'>结果</b><pre id='tune-result-pre'></pre></div>
      <div class='panel'><b class='title'>Trial 实时监控（每 3 秒刷新；收敛曲线 = cost 随 trial 下降）</b>
        <div id='tune-trials-info' class='muted'></div>
        <div id='tune-trials-chart'></div>
        <table id='tune-trials-table'><thead><tr><th>#</th><th>cost</th><th>参数</th><th>指标</th></tr></thead><tbody></tbody></table></div>`;
  T.$("tune-go").onclick = startTune;
  T.$("tune-path").onchange = showRecipeInfo;
  clearInterval(tuneTimer);
  tuneTimer = setInterval(pollTune, 3000);
  pollTune();
  showRecipeInfo();

  async function showRecipeInfo() {
    const d = await T.api("/api/recipes");
    const r = (d.recipes || []).find((x) => x.path === T.$("tune-path").value.trim());
    T.$("tune-recipe-info").innerHTML = r
      ? `已选配方：<b>${esc(r.model)}</b>，${esc(r.n_params)} 个参数，${esc(r.n_objectives)} 个目标，频段 ${esc(JSON.stringify(r.freq_range))}。要素含义见「配方编辑」页底部说明。`
      : "配方路径未在目录中找到，加载后仍可运行。";
  }
  async function startTune() {
    const r = await T.api("/api/tune/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: T.$("tune-path").value.trim(),
                             adapter: T.$("tune-adapter").value,
                             max_trials: parseInt(T.$("tune-trials").value) || 30,
                             sampler: T.$("tune-sampler").value }),
    });
    if (!r.ok) return T.msg(r.error, false);
    T.msg("调参已启动，状态轮询中...", true);
  }
  async function pollTune() {
    if (!T.$("view-tune") || T.$("view-tune").style.display === "none") return;
    const st = await T.api("/api/tune/status");
    T.$("tune-spin").innerHTML = st.running ? "<span class='spin'></span> 运行中" : "";
    T.$("tune-go").disabled = !!st.running;
    if (!st.running && (st.result || st.error)) {
      clearInterval(tuneTimer);
      T.$("tune-result").style.display = "";
      if (st.error) T.$("tune-result-pre").textContent = "错误: " + st.error;
      else T.$("tune-result-pre").textContent = JSON.stringify(st.result, null, 2);
    }
    renderTrials(st);
  }

  // trial 级实时监控：读 runs/<run_id>/trials/*.json（服务端聚合）
  async function renderTrials(st) {
    const info = T.$("tune-trials-info");
    if (!info) return;
    const d = await T.api("/api/tune/trials");
    const trials = d.trials || [];
    if (!trials.length) {
      info.textContent = "暂无 trial 数据（启动调参后这里实时出点）";
      return;
    }
    info.innerHTML = `run <b>${esc(d.run_id)}</b> · 已完成 ${trials.length} trials`
      + (st?.running ? " · <span class='spin'></span> 进行中" : "");
    // 收敛曲线（cost 随 trial）——PR-3 PlotCard convergence 模式：
    // best-so-far 阶梯线 + 终值 markLine + 末点（option 为声明增量）
    T.plotCard(T.$("tune-trials-chart"), {
      series: [{
        x: trials.map((t) => t.trial_number),
        y: trials.map((t) => t.cost),
        name: "cost",
      }],
      mode: "convergence",
      height: "220px", xlabel: "trial", ylabel: "cost",
      exportName: "tune-cost-convergence",
      ariaLabel: "图表：cost，纵轴 cost，横轴 trial（含 best-so-far 阶梯）",
    });
    // 最近 12 条（新→旧）
    const tb = T.$("tune-trials-table").tBodies[0];
    tb.innerHTML = trials.slice(-12).reverse().map((t) => {
      const params = Object.entries(t.params || {})
        .map(([k, v]) => `${esc(k)}=${typeof v === "number" ? v.toFixed(3) : esc(v)}`).join("  ");
      const metrics = Object.entries(t.metrics || {})
        .map(([k, v]) => `${esc(k)}=${typeof v === "number" ? v.toFixed(3) : esc(v)}`).join("  ");
      return `<tr><td>${esc(t.trial_number)}</td><td>${esc(typeof t.cost === "number" ? t.cost.toFixed(4) : "-")}</td>
        <td class="muted">${params}</td><td class="muted">${metrics}</td></tr>`;
    }).join("");
  }
}

/* ═══ Run 历史（指标筛选）═══ */
async function pageRuns() {
  const v = T.$("view-runs");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>每一行 = 一次仿真（run）。点击行进入详情：S 参数曲线（可切分量）、3D 模型、产物、配方快照。</li>
      <li>顶部筛选：按 run_id 文本、通道、S11 阈值过滤（如只看 -20dB 以下的）。</li>`) +
    `<h2 class='page'>Run 历史</h2>
      <div class='panel'><div class='toolbar'>
        <input id='f-text' size='18' placeholder='run_id 过滤…'>
        <select id='f-adapter'><option value=''>全部通道</option><option>fake</option><option>openems</option><option>hfss</option></select>
        S11 优于: <input id='f-s11' size='8' placeholder='-20'> dB
        <button class='minor' id='f-clear'>清除</button>
        <span id='f-count' class='muted'></span>
      </div>
      <table id='runs-table'><thead>
        <tr><th>run_id</th><th>时间</th><th>adapter</th><th>带内 S11</th><th>状态</th><th>best 指标</th></tr>
      </thead><tbody></tbody></table></div>`;
  const data = await T.api("/api/runs");
  S.allRuns = data.runs || [];
  const render = () => {
    const ft = T.$("f-text").value.trim().toLowerCase();
    const fa = T.$("f-adapter").value;
    const fs = parseFloat(T.$("f-s11").value);
    const rows = S.allRuns.filter((r) => {
      if (ft && !(r.run_id || "").toLowerCase().includes(ft)) return false;
      if (fa && r.adapter !== fa) return false;
      const m11 = r.metrics?.s11_db_max_in_band;
      if (!isNaN(fs) && !(typeof m11 === "number" && m11 <= fs)) return false;
      return true;
    });
    T.$("f-count").textContent = `${rows.length} / ${S.allRuns.length}`;
    const tb = T.$("runs-table").tBodies[0];
    tb.innerHTML = "";
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.className = "clickable";
      const metrics = r.metrics
        ? Object.entries(r.metrics).map(([k, v2]) => `${esc(k)}=${typeof v2 === "number" ? v2.toFixed(3) : esc(v2)}`).join(" ")
        : "";
      const m11 = r.metrics?.s11_db_max_in_band;
      tr.innerHTML = `<td>${esc(r.run_id || "")}</td><td>${esc(r.timestamp || r.ts || "")}</td><td>${esc(r.adapter || "")}</td><td>${esc(typeof m11 === "number" ? m11.toFixed(2) + " dB" : "-")}</td><td>${T.badge(r.status || "done", "muted")}</td><td class="muted">${metrics}</td>`;
      tr.onclick = () => { S.currentRunId = r.run_id; showPage("detail"); };
      tb.appendChild(tr);
    }
    if (!rows.length)
      tb.innerHTML = '<tr><td colspan="6" class="muted">无匹配 run</td></tr>';
  };
  ["f-text", "f-adapter", "f-s11"].forEach((id) => {
    T.$(id).oninput = render;
    T.$(id).onchange = render;
  });
  T.$("f-clear").onclick = () => {
    T.$("f-text").value = ""; T.$("f-adapter").value = ""; T.$("f-s11").value = "";
    render();
  };
  render();
}

/* ═══ Run 详情（ECharts 交互曲线，图例切换分量）═══ */
async function showRun(runId) {
  const id = runId || S.currentRunId;
  if (!id) return;
  S.currentRunId = id;
  T.activate("detail");
  const v = T.$("view-detail");
  if (!v.innerHTML)
    v.innerHTML = `<h2 class='page'>Run 详情 <small id='detail-id'></small></h2>
      <div class='panel' id='detail-head'></div>
      <div class='grid2'>
        <div class='panel'><b class='title'>S 参数（图例点击切换分量；滚轮缩放、悬停读数）</b>
          <div id='splot-echart'></div></div>
        <div class='panel'><b class='title'>3D 模型</b><div id='detail-3d'></div></div>
      </div>
      <div class='panel'><b class='title'>产物清单</b><table id='files-table'><thead><tr><th>文件</th><th>大小</th></tr></thead><tbody></tbody></table></div>
      <div class='panel'><b class='title'>配方快照</b><pre id='detail-recipe'></pre></div>`;
  const d = await T.api("/api/runs/" + id);
  if (!d.ok) return T.msg((d.errors || []).join("; "), false);
  T.$("detail-id").textContent = d.run_id;
  const m = d.metrics || {};
  T.$("detail-head").innerHTML =
    Object.entries(m).map(([k, v2]) =>
      `<span class="badge muted" style="margin-right:8px">${esc(k)}: <b style="color:var(--fg)">${typeof v2 === "number" ? v2.toFixed(4) : esc(v2)}</b></span>`).join("");
  const ftb = T.$("files-table").tBodies[0];
  ftb.innerHTML = "";
  for (const f of d.files || []) {
    const tr = document.createElement("tr");
    const kb = f.size_bytes > 1048576 ? (f.size_bytes / 1048576).toFixed(1) + " MB"
      : (f.size_bytes / 1024).toFixed(1) + " KB";
    tr.innerHTML = `<td>${esc(d.run_dir)}/${esc(f.path)}</td><td>${kb}</td>`;
    ftb.appendChild(tr);
  }
  T.$("detail-recipe").textContent = d.recipe_snapshot || "(无快照)";

  if ((d.sparams || []).length) {
    // PR-3 PlotCard 换壳 + crosshair（声明增量：tooltip.axisPointer cross）
    T.plotCard(T.$("splot-echart"), {
      series: d.sparams.map((c) => ({
        x: c.freq_ghz.map((f) => +f.toFixed(4)), y: c.db,
        name: `${c.name || c.file}`,
      })),
      height: "320px", xlabel: "GHz", ylabel: "dB",
      crosshair: true, exportName: "run-sparams",
    });
  } else {
    T.$("splot-echart").innerHTML = '<span class="muted">无 Touchstone（fake 通道），曲线图：</span>';
    for (const f of d.figs || []) {
      const img = document.createElement("img");
      img.src = "/" + f;
      img.style.cssText = "max-width:100%;display:block;margin:6px 0;border-radius:4px;cursor:zoom-in";
      img.onclick = () => T.lightboxImg("/" + f, f.split("/").pop());
      T.$("splot-echart").appendChild(img);
    }
  }
  T.drawBoxes(T.$("detail-3d"), d.model3d || { ok: false, errors: ["该 run 无可渲染的 3D 模板"] });
}

/* ═══ Agent 助手（设置 + 收件箱 diff + 浮动可拖拽对话卡片）═══ */
async function pageAgent() {
  const v = T.$("view-agent");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li><b>⚙ 模型设置</b>：填 OpenAI 兼容 API（base_url/model/api_key，如 deepseek、gpt、本地 ollama）并保存后，对话即切换为真实 LLM——它能调用框架工具（查 run、诊断、校验配方、生成参数提案）。</li>
      <li>未配置时为<b>指令模式</b>：直接发 "list runs"、"validate recipes/xxx.yaml"、"diagnose run_id" 等指令。</li>
      <li><b>安全边界</b>：agent 的工具大多是只读的；唯一会写盘的是「参数提案」——只写 recipes/ 下的提案文件，且必须走三层 Gate + 你在收件箱批准（diff 形式展示改了什么）才生效。<b>它接触不到框架源码</b>。</li>
      <li>内置系统提示词见下方「内置提示词」折叠块（完全透明）。</li>`) +
    `<h2 class='page'>Agent 助手</h2>
      <div class='panel'><div class='toolbar'>
        <b>⚙ 模型设置</b>
        base_url: <input id='chat-url' size='28' placeholder='https://api.xxx.com/v1'>
        model: <input id='chat-model' size='16' placeholder='模型名'>
        api_key: <input id='chat-key' size='18' type='password' placeholder='不改则留空'>
        <button class='act' id='chat-save'>保存</button>
        <button class='minor' id='chat-clear'>清空对话</button>
        <span id='chat-cfg-badge'></span>
      </div>
      <details class='help' style='margin:0'><summary>内置提示词（系统 prompt，透明可查）</summary>
        <pre id='chat-prompt' style='max-height:200px'></pre></details></div>
      <div class='panel'><b class='title'>审批收件箱（提案以参数 diff 展示）</b><div id='inbox-list' class='muted'>加载中...</div></div>
      <div class='panel'><b class='title'>Agent 沙箱草稿（agent 自主编辑先落沙箱；送审批走三层 Gate 进收件箱）</b>
        <div id='sandbox-list' class='muted'>加载中...</div></div>
      <div class='panel'><button class='act' id='chat-open'>💬 打开对话浮窗</button>
        <span class="muted">浮窗可拖拽（按住标题栏）、右下角缩放、可最小化，位置自动记忆。</span></div>`;
  T.$("chat-open").onclick = () => openChatFloat(true);
  T.$("chat-clear").onclick = async () => {
    await T.api("/api/chat/reset", { method: "POST" });
    const log = document.getElementById("chat-log");
    if (log) log.innerHTML = "";
    S.chatLog = [];
    localStorage.removeItem("rfauto-chat");
  };
  T.$("chat-save").onclick = async () => {
    const r = await T.api("/api/chat/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: T.$("chat-url").value.trim(),
                             model: T.$("chat-model").value.trim(),
                             api_key: T.$("chat-key").value }),
    });
    T.msg(r.ok ? "模型设置已保存" : "保存失败", !!r.ok);
    loadCfgBadge();
  };
  loadCfgBadge();
  const pr = await T.api("/api/chat/prompt");
  T.$("chat-prompt").textContent = pr.prompt || "(未取到)";
  await loadInbox();
  await loadSandbox();
  S.chatLog = JSON.parse(localStorage.getItem("rfauto-chat") || "[]");
  openChatFloat(false);
  for (const m of S.chatLog) appendBubble(m.who, m.text, m.tools);
  await updateStats();
  // 快捷提问 chips（点选即发送）
  const QUICK = ["分析最近一次 run", "list solvers", "校验 recipes/wilkinson_pd_v1.yaml",
                 "帮 wilkinson 配方提议一组新参数"];
  const q = document.getElementById("chat-suggest");
  if (q) {
    q.style.display = "flex";
    for (const t of QUICK) {
      const b = document.createElement("button");
      b.className = "chipbtn";
      b.textContent = t;
      b.onclick = () => { T.$("chat-in").value = t; sendChat(); };
      q.appendChild(b);
    }
  }

  function appendBubble(who, text, tools) {
    const log = document.getElementById("chat-log");
    if (!log) return;
    const md = who === "bot" && window.marked;
    log.insertAdjacentHTML("beforeend", `<div class='bubble ${who}${md ? " md" : ""}'></div>`);
    const el = log.lastChild;
    if (md) {
      // D-05：净化不可用时 renderMarkdown 内部降级 textContent（零注入）
      renderMarkdown(el,
        window.marked.parse(String(text), { breaks: true }));
    } else el.textContent = text;
    if (tools?.length) {
      el.insertAdjacentHTML("beforeend",
        `<div class="muted" style="font-size:11px;margin-top:4px">🔧 工具: ${esc([...new Set(tools)].join(" → "))}</div>`);
    }
    log.scrollTop = log.scrollHeight;
  }
  async function updateStats() {
    let stats;
    try { stats = (await T.api("/api/chat/stats")).stats; }
    catch { return; }
    const bar = document.getElementById("chat-stats");
    if (!bar) return;
    const fmt = (s2) => s2 >= 60 ? `${Math.floor(s2 / 60)}m${Math.round(s2 % 60)}s` : `${s2.toFixed(1)}s`;
    const hit = stats.prompt_tokens
      ? ` · 缓存命中 ${Math.round(stats.cached_tokens / stats.prompt_tokens * 100)}%` : "";
    bar.textContent = `轮数 ${stats.turns} · LLM ${fmt(stats.llm_elapsed_s)}（${stats.llm_calls} 次调用）`
      + ` · 工具 ${stats.tool_calls} 次耗时 ${fmt(stats.tool_elapsed_s)}`
      + ` · 输入 ${stats.prompt_tokens} tok · 输出 ${stats.completion_tokens} tok${hit}`;
  }
  /* 浮动对话卡片：拖拽 + 缩放 + 最小化，几何记忆 */
  function openChatFloat(focus = true) {
    let win = document.getElementById("chat-float");
    if (win) { win.style.display = "flex"; if (focus) document.getElementById("chat-in")?.focus(); return; }
    const geo = Object.assign({ x: Math.max(0, window.innerWidth - 620), y: 90, w: 560, h: 560, min: false },
      JSON.parse(localStorage.getItem("rfauto-chat-geo") || "{}"));
    win = document.createElement("div");
    win.id = "chat-float";
    win.setAttribute("role", "dialog"); // PR-1 a11y：非模态浮窗也补 dialog 语义
    win.setAttribute("aria-label", "Agent 对话浮窗");
    win.style.cssText = `position:fixed;z-index:50;display:flex;flex-direction:column;
      background:var(--panel);border:1px solid var(--border);border-radius:12px;
      box-shadow:var(--shadow);overflow:hidden`;
    win.innerHTML = `
      <div id="cf-head" style="display:flex;align-items:center;gap:8px;padding:8px 12px;
           background:var(--panel2);cursor:move;user-select:none">
        <b style="flex:1;font-size:13px;color:var(--accent)">💬 对话（历史自动保存）</b>
        <button class="minor" id="cf-min" style="padding:1px 8px">—</button>
        <button class="minor" id="cf-close" style="padding:1px 8px">×</button>
      </div>
      <div id="chat-log" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:8px;padding:10px"></div>
      <div id="chat-suggest" class="toolbar" style="margin:0;padding:0 10px"></div>
      <div class="toolbar" style="margin:0;padding:6px 10px">
        <input id='chat-in' style='flex:1' placeholder='例如：分析最近一次 run 并提议参数修改'>
        <button class='act' id='chat-send'>发送</button>
      </div>
      <div id="chat-stats" class="muted" style="font-size:11px;padding:0 10px 6px"></div>
      <div id="cf-resize" style="position:absolute;right:0;bottom:0;width:16px;height:16px;
           cursor:nwse-resize;background:linear-gradient(135deg,transparent 50%,var(--accent) 50%)"></div>`;
    document.body.appendChild(win);
    const head = win.querySelector("#cf-head");
    const apply = () => {
      win.style.left = geo.x + "px"; win.style.top = geo.y + "px";
      win.style.width = geo.w + "px";
      win.style.height = geo.min ? "44px" : geo.h + "px";
      const body = win.querySelector("#chat-log");
      body.style.display = geo.min ? "none" : "";
      ["chat-suggest", "chat-stats"].forEach((id2) => {
        const e2 = win.querySelector("#" + id2);
        if (e2) e2.style.display = geo.min ? "none" : "";
      });
      const tb = win.querySelector(".toolbar");
      if (tb && tb !== head) tb.style.display = geo.min ? "none" : "";
    };
    apply();
    head.onpointerdown = (e) => {
      if (e.target.tagName === "BUTTON") return;
      const sx = e.clientX - geo.x, sy = e.clientY - geo.y;
      const mv = (ev) => {
        geo.x = Math.max(0, ev.clientX - sx); geo.y = Math.max(0, ev.clientY - sy);
        apply();
      };
      const up = () => { window.removeEventListener("pointermove", mv);
        window.removeEventListener("pointerup", up);
        localStorage.setItem("rfauto-chat-geo", JSON.stringify(geo)); };
      window.addEventListener("pointermove", mv);
      window.addEventListener("pointerup", up);
    };
    win.querySelector("#cf-resize").onpointerdown = (e) => {
      e.stopPropagation();
      const sw = geo.w, sh = geo.h, sx = e.clientX, sy = e.clientY;
      const mv = (ev) => {
        geo.w = Math.max(380, sw + ev.clientX - sx);
        geo.h = Math.max(260, sh + ev.clientY - sy);
        apply();
      };
      const up = () => { window.removeEventListener("pointermove", mv);
        window.removeEventListener("pointerup", up);
        localStorage.setItem("rfauto-chat-geo", JSON.stringify(geo)); };
      window.addEventListener("pointermove", mv);
      window.addEventListener("pointerup", up);
    };
    win.querySelector("#cf-min").onclick = () => { geo.min = !geo.min; apply();
      localStorage.setItem("rfauto-chat-geo", JSON.stringify(geo)); };
    win.querySelector("#cf-close").onclick = () => { win.style.display = "none"; };
    win.querySelector("#chat-send").onclick = sendChat;
    win.querySelector("#chat-in").onkeydown = (e) => { if (e.key === "Enter") sendChat(); };
    if (focus) document.getElementById("chat-in")?.focus();
    for (const m of S.chatLog) appendBubble(m.who, m.text, m.tools);
  }

  async function loadCfgBadge() {
    const cfg = await T.api("/api/chat/settings");
    T.$("chat-url").value = cfg.base_url || "";
    T.$("chat-model").value = cfg.model || "";
    T.$("chat-cfg-badge").innerHTML = cfg.configured
      ? T.badge("已配置真实 LLM", "ok") : T.badge("未配置（指令模式）", "muted");
  }

  /* 提案 → 参数 diff 表（当前配方值 vs 提案值） */
  async function renderProposal(p) {
    const div = document.createElement("div");
    div.className = "panel";
    div.style.marginBottom = "10px";
    const recipePath = p.recipe || "";
    let rows = "";
    try {
      const cur = await T.api("/api/recipe?path=" + encodeURIComponent(recipePath));
      const base = {};
      for (const x of cur.params || []) base[x.name] = x.value;
      const params = p.params || {};
      rows = Object.entries(params).map(([n, nv]) => {
        const old = base[n];
        const changed = old !== undefined && old !== nv;
        const pct = (typeof old === "number" && typeof nv === "number" && old)
          ? ` (${nv > old ? "+" : ""}${((nv - old) / old * 100).toFixed(1)}%)` : "";
        const cls = changed ? "color:var(--warn)" : "";
        return `<tr><td><b>${esc(n)}</b></td><td class="muted">${esc(old ?? "(新增)")}</td>
          <td style="${cls}">${esc(nv)}${pct}</td></tr>`;
      }).join("");
    } catch {
      rows = `<tr><td colspan="3" class="muted">当前配方值不可读，仅列提案值</td></tr>` +
        Object.entries(p.params || {}).map(([n, nv]) => `<tr><td><b>${esc(n)}</b></td><td>-</td><td>${esc(nv)}</td></tr>`).join("");
    }
    div.innerHTML = `<b>${escAttr(recipePath)}</b> ${T.badge("参数提案", "warn")}
      <table><thead><tr><th>参数</th><th>当前值</th><th>提案值</th></tr></thead><tbody>${rows}</tbody></table>
      <div class="toolbar" style="margin-top:8px"><button class='act'>批准并执行</button>
      <span class="muted">token: ${escAttr(p.token_hash || "")}</span></div>`;
    div.querySelector("button").onclick = async () => {
      const r = await T.api("/api/inbox/approve", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token_hash: p.token_hash, recipe: recipePath, adapter: "fake" }),
      });
      T.msg(r.ok ? "已批准并执行" : "审批失败: " + (r.error || r.errors?.join("; ") || ""), !!r.ok);
      loadInbox();
    };
    return div;
  }

  async function loadInbox() {
    const d = await T.api("/api/inbox");
    const el = T.$("inbox-list");
    if (!(d.pending || []).length) { el.innerHTML = "<span class='muted'>无待审批提案</span>"; return; }
    el.innerHTML = "";
    for (const p of d.pending)
      el.appendChild(await renderProposal(p));
  }

  /* Agent 沙箱草稿：列表 + 参数差异 + unified diff + 送审批 */
  async function loadSandbox() {
    const el = T.$("sandbox-list");
    if (!el) return;
    const d = await T.api("/api/sandbox/drafts");
    if (!d.ok) { el.innerHTML = "<span class='muted'>沙箱状态不可读</span>"; return; }
    if (!(d.drafts || []).length) {
      el.innerHTML = "<span class='muted'>无沙箱草稿（agent 在对话中编辑配方后会出现在这里）</span>";
      return;
    }
    el.innerHTML = "";
    for (const item of d.drafts) {
      const div = document.createElement("div");
      div.className = "panel";
      div.style.marginBottom = "10px";
      const changed = Object.entries(item.params_changed || {});
      const rows = changed.length
        ? changed.map(([n, c]) =>
            `<tr><td><b>${esc(n)}</b></td><td class="muted">${esc(c.old ?? "(新增)")}</td><td style="color:var(--warn)">${esc(c.new ?? "(删除)")}</td></tr>`).join("")
        : `<tr><td colspan="3" class="muted">无参数差异${item.recipe ? "" : "（草稿未匹配到 recipes/ 源配方）"}</td></tr>`;
      div.innerHTML = `<b>${escAttr(item.draft.split(/[\\/]/).pop())}</b>
        ${item.recipe ? T.badge(item.recipe, "ok") : T.badge("来源未匹配", "muted")}
        <table><thead><tr><th>参数</th><th>当前值</th><th>草稿值</th></tr></thead><tbody>${rows}</tbody></table>
        <div class="toolbar" style="margin-top:8px">
          ${item.recipe ? `<button class='minor' data-act='diff'>查看 diff</button>
          <button class='act' data-act='promote'>送审批（进收件箱）</button>` : ""}
          <span class="muted">promote 只放行 params 差异，其余节差异会被 Gate 拒绝</span></div>
        <pre data-role='diffbox' style='display:none;max-height:260px;overflow:auto'></pre>`;
      const diffBtn = div.querySelector("[data-act='diff']");
      if (diffBtn) diffBtn.onclick = async () => {
        const box = div.querySelector("[data-role='diffbox']");
        if (box.style.display === "none") {
          const r = await T.api("/api/sandbox/diff?recipe=" + encodeURIComponent(item.recipe));
          box.textContent = r.ok ? (r.unified_diff || "(无文本差异)") : (r.error || "diff 失败");
          box.style.display = "";
          diffBtn.textContent = "收起 diff";
        } else { box.style.display = "none"; diffBtn.textContent = "查看 diff"; }
      };
      const promoteBtn = div.querySelector("[data-act='promote']");
      if (promoteBtn) promoteBtn.onclick = async () => {
        promoteBtn.disabled = true;
        const r = await T.api("/api/sandbox/promote", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ recipe: item.recipe }),
        });
        if (r.ok) {
          T.msg("已生成提案，等你在收件箱批准", true);
          loadInbox();
        } else {
          T.msg("promote 被拒: " + (r.error || (r.errors || []).join("; ") || "未知原因"), false);
          promoteBtn.disabled = false;
        }
      };
      el.appendChild(div);
    }
  }

  async function sendChat() {
    const inp = document.getElementById("chat-in"), log = document.getElementById("chat-log");
    const text = inp.value.trim();
    if (!text) return;
    inp.value = "";
    appendBubble("user", text);
    S.chatLog.push({ who: "user", text });
    localStorage.setItem("rfauto-chat", JSON.stringify(S.chatLog.slice(-100)));
    log.insertAdjacentHTML("beforeend",
      `<div class='bubble bot'><span class='spin'></span> 思考中（可能连续调用多个工具，约 10-60 秒，复杂任务可能更久）…</div>`);
    log.scrollTop = log.scrollHeight;
    const r = await T.api("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text }),
    });
    const reply = r.reply || r.response || r.text || JSON.stringify(r);
    log.lastChild.remove();
    appendBubble("bot", reply, r.tools);
    S.chatLog.push({ who: "bot", text: reply, tools: r.tools });
    localStorage.setItem("rfauto-chat", JSON.stringify(S.chatLog.slice(-100)));
    await updateStats();
    if (r.action && r.action !== "chat" && r.action !== "unknown") loadInbox();
  }
}

/* ═══ 求解器 ═══ */
async function pageSolvers() {
  const v = T.$("view-solvers");
  v.innerHTML = help(`
    <li><b>求解器</b> = 实际执行电磁仿真的引擎。openEMS：免费开源 FDTD（当前可用）；Palace：有限元（未装则不可用）。</li>
    <li>HFSS 走商业 license，2023.1 为已验证真机通道；在「配方编辑」运行按钮旁或「优化调参」的 adapter 下拉中选择。</li>
    <li>「可视化 N 个」= 该求解器能产出的补充视图数量。</li>`) +
    "<h2 class='page'>求解器</h2><div class='panel'><b class='title'>注册状态</b><div id='sv-body' class='muted'>加载中...</div></div>";
  const d = await T.api("/api/solvers");
  const viz = await T.api("/api/solvers/viz");
  T.$("sv-body").innerHTML =
    `<table><thead><tr><th>类型</th><th>类</th><th>可用</th><th>可视化</th></tr></thead><tbody>` +
    (d.solvers || []).map((s) =>
      `<tr><td><b>${esc(s.type)}</b></td><td class="muted">${esc(s.class)}</td><td>${s.available ? T.badge("可用", "ok") : T.badge("不可用", "err")}</td><td>${esc(s.n_visualizations)}</td></tr>`).join("") +
    `</tbody></table><pre>${esc(JSON.stringify(viz, null, 2))}</pre>`;
}

/* ═══ 微波工具箱（E4 计算器：数值只在确定性内核）═══ */

/* 计算器中文名兜底表（项 5 双语面板）：describe() 的 description 本身以
   "中文名：用途" 开头，正常从冒号前提取；此表只在 description 缺中文时兜底，
   并给下拉 "key（中文名）" 稳定展示。键=注册表 name，值=[中文名, 用途一句]。 */
const CALC_ZH = {
  attenuator_bridged_t: ["桥式 T 型衰减器", "给定衰减量/Z0 → 桥式 T 网络电阻值"],
  attenuator_pi: ["π 型衰减器", "给定衰减量/Z0 → π 网络电阻值"],
  attenuator_t: ["T 型衰减器", "给定衰减量/Z0 → T 网络电阻值"],
  cavity_perturbation_shift: ["腔体微扰谐振频移", "小样品/形变引起的谐振频率偏移估算"],
  chebyshev_prototype: ["Chebyshev 低通原型", "阶数/纹波 → 归一化 g 元件值"],
  chebyshev_prototype_asym: ["Chebyshev 非对称原型", "非对称端接的低通原型元件值"],
  chebyshev_refl_fn: ["Chebyshev 反射函数", "等纹波反射特性函数取值"],
  coupling_matrix_arrow: ["箭头拓扑耦合矩阵", "N+2 耦合矩阵折到箭头形拓扑"],
  coupling_matrix_extract: ["耦合矩阵提取", "从响应/多项式反推耦合矩阵"],
  coupling_matrix_folded: ["折叠拓扑耦合矩阵", "N+2 耦合矩阵折到折叠形拓扑"],
  coupling_matrix_response: ["耦合矩阵响应", "给定耦合矩阵 → S11/S21 频响"],
  coupling_matrix_synthesize_explicit: ["耦合矩阵综合（显式）", "由指定多项式显式综合耦合矩阵"],
  coupling_matrix_synthesize_n2: ["耦合矩阵综合（N+2）", "滤波器规格 → N+2 横向耦合矩阵"],
  cps_analysis: ["共面带状线 CPS 分析", "几何 → Z0/εeff"],
  cps_synthesis: ["共面带状线 CPS 综合", "目标 Z0 → 几何尺寸"],
  cpw_analysis: ["共面波导 CPW 分析", "中心导带宽/缝宽 → Z0/εeff"],
  cpw_synthesis: ["共面波导 CPW 综合", "目标 Z0 → 中心导带宽/缝宽"],
  cpwg_analysis: ["接地共面波导 CPWG 分析", "带底地 CPW 几何 → Z0/εeff"],
  cpwg_synthesis: ["接地共面波导 CPWG 综合", "目标 Z0 → 带底地 CPW 几何"],
  ecss_multipactor_fd: ["ECSS 微放电频域判据", "间隙×频率 → 微放电击穿裕度（ECSS 口径）"],
  ipc2152_trace_temp_rise: ["IPC-2152 走线温升", "电流/线宽/铜厚 → 走线温升估算"],
  microstrip_analysis: ["微带线分析", "线宽 → Z0/εeff（skrf Hammerstad-Jensen）"],
  microstrip_lambda_g: ["微带导波波长 λg", "几何/频率 → εeff、λ0、λg"],
  microstrip_loss_heat: ["微带损耗与发热", "导体/介质损耗 → 单位长度耗散功率"],
  microstrip_synthesis: ["微带线综合", "目标 Z0 → 线宽（求逆+自洽回代）"],
  parallel_plate_breakdown_margin: ["平行板击穿裕度", "间隙/电压 → 击穿场强裕度"],
  patch_f0_symbolic_e13: ["贴片谐振频率（符号回归，实验）", "自动归纳经验式，默认不放行"],
  patch_length: ["贴片谐振长度", "目标频率/基板 → 贴片长度（Balanis 闭式）"],
  quarter_wave_transformer: ["λ/4 阻抗变换器", "两端阻抗 → 变换段 Z0 与长度"],
  resonator_thermal_drift: ["谐振器热漂移", "温度变化 → 谐振频率漂移"],
  stripline_analysis: ["带状线分析", "线宽/介质厚 → Z0"],
  stripline_synthesis: ["带状线综合", "目标 Z0 → 线宽"],
  suspended_stripline_analysis: ["悬置带状线分析", "悬置结构几何 → Z0/εeff"],
  suspended_stripline_synthesis: ["悬置带状线综合", "目标 Z0 → 悬置结构几何"],
  thermal_resistance_stack: ["叠层热阻", "多层材料/厚度 → 总热阻与温升"],
  vswr_convert: ["驻波/反射换算", "VSWR ↔ |Γ| ↔ 回波损耗 dB 互换"],
};
const _HAS_CJK = /[\u4e00-\u9fff]/;

/* 计算器中文名：优先 description 冒号前缀（注册表自带中文），否则查兜底表，再退 key */
function calcZhName(c) {
  const head = String(c.description || "").split(/[：:]/)[0].trim();
  if (head && _HAS_CJK.test(head) && head.length <= 24) return head;
  return (CALC_ZH[c.name] || [])[0] || c.name;
}
/* 参数说明 "类型 单位 中文说明" → {unit, text}；单位 "-" 视为无量纲 */
function parseParamDesc(desc) {
  const t = String(desc || "").trim().split(/\s+/);
  if (t.length >= 3 && /^(float|int|str|bool|list|dict)$/i.test(t[0])) {
    return { unit: t[1] === "-" ? "" : t[1], text: t.slice(2).join(" ") };
  }
  return { unit: "", text: String(desc || "") };
}

async function pageTools() {
  const v = T.$("view-tools");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>闭式微波计算器：微带/CPW/带状线正反解、λ/4 变换、π/T 衰减器、驻波换算、λg、贴片谐振长度。</li>
      <li>与综合引擎同口径（skrf Hammerstad-Jensen / Balanis 闭式）；必填参数标 *，留空的可选参数不传。</li>
      <li>同一 service 也开放在 CLI（rfauto calc）与 MCP（run_calculator）——三壳一个内核。</li>`) +
    `<h2 class='page'>微波工具箱</h2>
     <div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>
       <div class='panel' style='flex:1;min-width:380px'>
         <div class='toolbar'><b>计算器</b>
           <select id='tool-name' style='flex:1'></select></div>
         <div id='tool-desc' class='muted' style='margin:8px 0;padding:8px;border:1px solid var(--border);border-radius:6px'></div>
         <div id='tool-params'></div>
         <div class='toolbar' style='margin-top:10px'>
           <button id='tool-run' class='primary'>计算</button>
           <span id='tool-msg' class='muted'></span></div>
       </div>
       <div class='panel' style='flex:1;min-width:320px'><b class='title'>结果</b>
         <div id='tool-result' class='muted'>选择计算器，填参数后点「计算」</div></div>
     </div>`;
  const d = await T.api("/api/calculators");
  const cals = d.calculators || [];
  const sel = T.$("tool-name");
  sel.innerHTML = cals
    .map((c) => `<option value="${escAttr(c.name)}">${esc(c.name)}（${esc(calcZhName(c))}）${c.experimental ? " [实验]" : ""}</option>`)
    .join("");
  const renderParams = () => {
    const cal = cals.find((c) => c.name === sel.value) || { params: [] };
    // 双语说明面板（项 5）：中文名 + 用途（description 透传）+ 实验态 + 英文 key
    const zh = calcZhName(cal);
    const purpose = String(cal.description || "").replace(/^[^：:]*[：:]\s*/, "")
      || (CALC_ZH[cal.name] || [])[1] || "";
    T.$("tool-desc").innerHTML =
      `<b style='color:var(--fg)'>${esc(zh)}</b> <code class='muted'>${esc(cal.name || "")}</code>` +
      (cal.experimental ? " " + T.badge("实验态（默认不放行）", "warn") : "") +
      (purpose ? `<div style='margin-top:4px'>${esc(purpose)}</div>` : "");
    T.$("tool-params").innerHTML = cal.params
      .map((p) => {
        const { unit, text } = parseParamDesc(p.desc);
        return `<label class='muted' style='display:block;margin:8px 0 2px'><b style='color:var(--fg)'>${esc(p.name)}</b>${p.required ? " <span style='color:var(--warn)'>*</span>" : ""}` +
          (unit ? ` <span class='badge muted'>${esc(unit)}</span>` : "") +
          ` <small>${esc(text)}</small>
        <input id='tool-p-${escAttr(p.name)}' style='width:100%' placeholder='${escAttr((p.required ? "必填" : "可选，留空不传") + (unit ? "（" + unit + "）" : ""))}'></label>`;
      })
      .join("");
  };
  sel.onchange = renderParams;
  renderParams();
  T.$("tool-run").onclick = async () => {
    const cal = cals.find((c) => c.name === sel.value) || { params: [] };
    const params = {};
    for (const p of cal.params) {
      const el = T.$("tool-p-" + p.name);
      if (!el || el.value.trim() === "") continue;
      const raw = el.value.trim();
      const num = Number(raw);
      params[p.name] = raw !== "" && !Number.isNaN(num) ? num : raw;
    }
    T.$("tool-msg").textContent = "计算中...";
    const r = await T.api("/api/calculators/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: sel.value, params }),
    });
    const box = T.$("tool-result");
    if (!r.ok) {
      T.$("tool-msg").textContent = "";
      box.innerHTML = `<span style='color:#e57373'>✗ ${esc(r.error)}</span>`;
      return;
    }
    T.$("tool-msg").textContent = "完成";
    box.innerHTML = "<table><tbody>" + Object.entries(r.result)
      .map(([k, val]) =>
        `<tr><td class='muted'>${esc(k)}</td><td><b>${esc(val)}</b></td></tr>`)
      .join("") + "</tbody></table>";
  };
}

/* ═══ 校准工作台（阶段 3.2）+ 跨保真演化（3.3 数据源同页）═══ */
async function pageCalibration() {
  const v = T.$("view-calibration");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>校准产物一览：每次 calibrate/augment 的 gate 判定、LOOCV ρ、样本量与网格档。</li>
      <li>点击行看详情：参数空间散点（cost 着色）、验证点偏差、报告全文。</li>
      <li>演化图：ρ 随样本量的收敛轨迹 + 跨保真 gate 历史——校准数据是资产，逐次增广都会点亮一个点。</li>`) +
    `<h2 class='page'>校准工作台</h2>
     <div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>
       <div class='panel' style='flex:1;min-width:340px'><div class='toolbar'><b>校准 run</b>
         <span id='cal-count' class='muted'></span></div>
         <table id='cal-table'><thead><tr><th>run_id</th><th>模型</th><th>判定</th><th>ρ</th><th>样本</th><th>mesh</th><th>代理</th></tr></thead><tbody></tbody></table></div>
       <div class='panel' style='flex:1;min-width:380px'><b>ρ 演化（样本量 ↔ 代理/跨保真 gate）</b>
         <div id='cal-evolution'></div>
         <div id='cal-gates' class='muted' style='margin-top:6px'></div></div>
     </div>
     <div id='cal-detail'></div>`;
  const [runs, evo] = await Promise.all([
    T.api("/api/calibration"), T.api("/api/cross_fidelity")]);
  const list = runs.runs || [];
  T.$("cal-count").textContent = `${list.length} 个`;
  const tbody = T.$("cal-table").querySelector("tbody");
  tbody.innerHTML = list.map((r) => {
    const b = r.verdict === "PASS" ? T.badge("PASS", "ok") : T.badge("FAIL", "err");
    return `<tr data-rid='${escAttr(r.run_id)}' style='cursor:pointer'>
      <td class='muted'>${esc(r.run_id)}</td><td>${esc(r.model || "?")}</td><td>${b}</td>
      <td>${r.rho == null ? "-" : (+r.rho).toFixed(3)}</td>
      <td>${esc(r.n_samples ?? "-")}</td>
      <td>${esc(r.mesh_resolution_mm == null ? "-" : r.mesh_resolution_mm)}</td>
      <td class='muted'>${esc(r.surrogate_kind || "-")}</td></tr>`;
  }).join("");
  for (const tr of tbody.querySelectorAll("tr"))
    tr.onclick = () => loadCalibration(tr.dataset.rid);

  const sur = (evo.surrogate_evolution || []).filter((e) => e.rho != null);
  const cro = (evo.cross_evolution || []).filter((e) => e.rho != null);
  // PR-1 对比度：显式系列色按主题分档（浅色档白底 ≥3:1，深色档不变）
  const light = document.body.classList.contains("light");
  // PR-3 PlotCard 换壳：option 与迁移前等价（base 路径，scatter+xvalue+markline）
  T.plotCard(T.$("cal-evolution"), {
    series: [
      { name: "代理 LOOCV ρ", type: "scatter", color: light ? "#0e8f74" : "#22d3a5",
        data: sur.map((e) => [e.n_samples, +e.rho]) },
      { name: "跨保真 gate ρ", type: "scatter", color: light ? "#0277bd" : "#4fc3f7",
        data: cro.map((e) => [e.n_evaluated, +e.rho]) },
    ],
    xvalue: true, xlabel: "样本量", ylabel: "ρ", zoom: false, height: "300px",
    markline: [{ yAxis: 0.8 }], exportName: "cal-evolution", exportCsv: false,
  });
  T.$("cal-gates").textContent = cro.length
    ? cro.map((e) => `${e.run_id}: ρ=${e.rho == null ? "-" : (+e.rho).toFixed(3)} ${e.verdict || ""}`).join(" · ")
    : "暂无跨保真 gate 记录";
}

async function loadCalibration(runId) {
  const d = await T.api("/api/calibration/" + encodeURIComponent(runId));
  const v = T.$("cal-detail");
  if (!d.ok) { v.innerHTML = `<div class='panel'>${esc((d.errors || []).join("; "))}</div>`; return; }
  const g = d.gate || {};
  const loocv = g.loocv || {};
  const keys = Object.keys(d.bounds || {}).sort();
  const costColor = (c) => {
    if (c == null) return "#8391a7";
    const cs = d.points.map((p) => p.cost).filter((x) => x != null);
    const lo = Math.min(...cs), hi = Math.max(...cs);
    const t = hi > lo ? (c - lo) / (hi - lo) : 0;
    return `rgb(${Math.round(40 + 200 * t)},${Math.round(190 - 130 * t)},${Math.round(120 - 60 * t)})`;
  };
  const xy = keys.length >= 2 ? keys.slice(0, 2) : [keys[0], null];
  const scatter = {
    name: "样本点", type: "scatter", symbolSize: 12,
    color: document.body.classList.contains("light") ? "#0277bd" : "#4fc3f7",
    data: d.points.map((p) => ({
      value: [p[xy[0]], xy[1] ? p[xy[1]] : p.cost],
      itemStyle: { color: costColor(p.cost) },
    })),
  };
  const valRows = (d.validation || []).map((val) => {
    if (val.error) return `<tr><td colspan='2' class='muted'>验证点失败: ${esc(val.error)}</td></tr>`;
    const deltas = Object.entries(val.abs_delta || {})
      .map(([k, x]) => `${esc(k)}=${(+x).toFixed(3)}`).join(" · ");
    return `<tr><td class='muted'>${esc(Object.values(val.params).map((x) => (+x).toFixed(2)).join(", "))}</td>
      <td>${esc(deltas)}</td></tr>`;
  }).join("");
  const report = d.report_md
    ? (window.marked && mdReady() ? mdSanitize(window.marked.parse(d.report_md))
      : `<pre>${esc(d.report_md)}</pre>`)
    : "<span class='muted'>无报告</span>";
  v.innerHTML = `
    <div class='panel'>
      <div class='toolbar'><b>校准详情 ${escAttr(runId)}</b>
        ${g.verdict === "PASS" ? T.badge("PASS", "ok") : T.badge("FAIL", "err")}
        <span class='muted'>ρ=${loocv.rho == null ? "-" : (+loocv.rho).toFixed(3)} ·
          样本 ${d.points.length}${d.seed_sample_count ? `（种子 ${d.seed_sample_count}）` : ""} ·
          mesh ${d.mesh_resolution_mm == null ? "-" : d.mesh_resolution_mm}mm</span></div>
      <div style='display:flex;gap:14px;flex-wrap:wrap'>
        <div style='flex:1;min-width:360px'><b>参数空间（${esc(xy[0])}${xy[1] ? " × " + esc(xy[1]) : ""}，颜色=cost 好→差）</b>
          <div id='cal-scatter'></div></div>
        <div style='flex:1;min-width:320px'><b>验证点偏差（预测 vs 实际）</b>
          <table><thead><tr><th>参数</th><th>|Δ| 指标</th></tr></thead><tbody>${valRows || "<tr><td class=muted>无</td></tr>"}</tbody></table></div>
      </div>
      <details><summary class='muted'>校准报告全文</summary><div class='muted'>${report}</div></details>
    </div>`;
  // PR-3 PlotCard 换壳：option 与迁移前等价（scatter+xvalue）
  T.plotCard(T.$("cal-scatter"), {
    series: [scatter],
    xvalue: true, xlabel: xy[0],
    ylabel: xy[1] || "cost", zoom: false, height: "320px",
    exportName: "cal-scatter", exportCsv: false,
  });
}

/* ═══ S 参数交互视图（阶段 3.1）═══ */
async function pageSparams() {
  const v = T.$("view-sparams");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>选一个 run，交互查看全部 S 参数曲线：图例点选隐藏/显示、滚轮+滑块缩放、悬停读数。</li>
      <li>dB 模式看匹配/损耗谷位；相位模式（解缠绕）看电长度/谐振行为。</li>
      <li>「+外部 .sNp」= 导入本机 Touchstone 文件与 run 产物叠加对比（WP0.3/E8，只读）；相位模式下叠加会清空以防量纲混淆。</li>
      <li>「Smith」= 各端口反射系数 S_ii 的 Smith 圆图（G9）：恒 r 圆/恒 x 弧为纯几何网格，悬停读频率与 Z=Z0(1+Γ)/(1−Γ)；|Γ|→1 时阻抗读数置 N/A。</li>
      <li>数据源 = run 产物 Touchstone；fake 通道无 Touchstone 时到「Run 详情」看 PNG 曲线。</li>`) +
    `<h2 class='page'>S 参数分析</h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='sp-run' style='max-width:340px'></select>
         <button class='minor' id='sp-mode-db'>dB</button>
         <button class='minor' id='sp-mode-deg'>相位</button>
         <button class='minor' id='sp-mode-smith'>Smith</button>
         <button class='minor' id='sp-add-ext'>+外部 .sNp</button>
         <button class='minor' id='sp-clear-ext'>清除叠加</button>
         <span id='sp-info' class='muted'></span></div>
       <div id='sp-charts'></div>
     </div>`;
  let mode = S.spMode || "db";
  const runs = (await T.api("/api/runs")).runs || [];
  const sel = T.$("sp-run");
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.model || "?")} · ${esc(r.adapter || "?")}）</option>`).join("");
  if (S.currentRunId) sel.value = S.currentRunId;
  if (S.spRunId) sel.value = S.spRunId;

  async function load() {
    S.spRunId = sel.value;
    const box = T.$("sp-charts");
    T.$("sp-info").textContent = "";
    if (mode === "smith") {
      // Smith 圆图（G9）：run 各文件 S_ii 轨迹 + 外部叠加轨迹，一张图
      const d = await T.api(`/api/smith/${encodeURIComponent(sel.value)}`);
      const overlays = (S.spOverlay || []).filter((o) => o.mode === "smith");
      const traces = (d.ok ? d.traces || [] : []).map((t) => ({ ...t, label: `${t.file}·${t.name}` }));
      for (const o of overlays)
        for (const t of o.traces || []) traces.push({ ...t, label: `ext:${o.file}·${t.name}` });
      if (!traces.length) {
        box.innerHTML = `<span class='muted'>${d.ok ? "该 run 无 Touchstone 产物" + (d.warning ? "（" + esc(d.warning) + "）" : "") : esc((d.errors || []).join("; "))}——可用「+外部 .sNp」导入</span>`;
        return;
      }
      if (d.warning) T.$("sp-info").textContent = `部分文件解析失败: ${d.warning}`;
      box.innerHTML = `<div id='sp-smith'></div>`;
      const grid = d.ok ? d.grid : (overlays[0] && overlays[0].grid);
      drawSmith(T.$("sp-smith"), traces, grid, d.ok ? d.z0 : (overlays[0] && overlays[0].z0));
      return;
    }
    const d = await T.api(`/api/sparams/${encodeURIComponent(sel.value)}?mode=${mode}`);
    // 外部叠加（WP0.3/E8）：只保留与当前模式同量纲的叠加曲线
    const overlays = (S.spOverlay || []).filter((o) => o.mode === mode);
    const runCurves = d.ok ? (d.curves || []) : [];
    if (!d.ok && !overlays.length) {
      box.innerHTML = `<span class='muted'>${esc((d.errors || []).join("; "))}</span>`;
      return;
    }
    if (!runCurves.length && !overlays.length) {
      box.innerHTML = `<span class='muted'>该 run 无 Touchstone 产物${d.warning ? "（" + esc(d.warning) + "）" : ""}——fake 通道请到 Run 详情页看 PNG 曲线，或用「+外部 .sNp」直接导入文件</span>`;
      return;
    }
    if (d.warning) T.$("sp-info").textContent = `部分文件解析失败: ${d.warning}`;
    // 同文件同频网成组；多文件时各画一张图（文件名标注在标题）
    const groups = {};
    for (const c of runCurves) (groups[c.file] = groups[c.file] || []).push(c);
    const multi = Object.keys(groups).length > 1;
    let html = overlays.length
      ? `<b class='muted'>对比图（run 产物 + 外部叠加）</b><div id='sp-chart-overlay' style='margin-bottom:12px'></div>`
      : "";
    html += Object.keys(groups).map((f) =>
      `<div style='margin-bottom:12px'>${multi ? `<b class='muted'>${esc(f)}</b>` : ""}<div id='sp-chart-${f.replace(/\W/g, "")}'></div></div>`).join("");
    if (!runCurves.length && overlays.length)
      html = `<b class='muted'>外部叠加（该 run 无 Touchstone 产物）</b><div id='sp-chart-overlay' style='margin-bottom:12px'></div>`;
    box.innerHTML = html;
    for (const [f, curves] of Object.entries(groups)) {
      const id = `sp-chart-${f.replace(/\W/g, "")}`;
      // PR-3 PlotCard 换壳 + crosshair（声明增量：axisPointer cross）
      T.plotCard(T.$(id), {
        series: curves.map((c) => ({
          name: c.name, x: c.freq_ghz, y: c.y,
        })),
        xlabel: "GHz", ylabel: mode === "db" ? "dB" : "相位（deg）",
        height: "340px", zoom: true,
        crosshair: true, exportName: "sparams-" + f.replace(/\W/g, "-"),
      });
    }
    if (overlays.length) {
      const series = [];
      for (const [f, curves] of Object.entries(groups))
        for (const c of curves) series.push({ name: `${f}·${c.name}`, x: c.freq_ghz, y: c.y });
      for (const o of overlays)
        for (const c of o.curves) series.push({ name: `ext:${o.file}·${c.name}`, x: c.freq_ghz, y: c.y });
      // PR-3 PlotCard 换壳 + crosshair（声明增量：axisPointer cross）
      T.plotCard(T.$("sp-chart-overlay"), {
        series,
        xlabel: "GHz", ylabel: mode === "db" ? "dB" : "相位（deg）",
        height: "360px", zoom: true,
        crosshair: true, exportName: "sparams-overlay",
      });
    }
  }
  T.$("sp-mode-db").onclick = () => { S.spMode = "db"; pageSparams(); };
  T.$("sp-mode-deg").onclick = () => { S.spMode = "deg"; pageSparams(); };
  T.$("sp-mode-smith").onclick = () => { S.spMode = "smith"; pageSparams(); };
  T.$("sp-add-ext").onclick = () => fileBrowser("", async (p) => {
    const smith = mode === "smith";
    const r = await T.api(smith ? "/api/smith/external" : "/api/sparams/external", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(smith ? { path: p } : { path: p, mode }),
    });
    if (!r.ok) { T.msg((r.errors || ["导入失败"]).join("; "), false); return; }
    const rmode = smith ? "smith" : r.mode;
    S.spOverlay = S.spOverlay || [];
    if (S.spOverlay.some((o) => o.path === r.path && o.mode === rmode)) {
      T.msg("该文件已叠加", false);
      return;
    }
    S.spOverlay.push({ path: r.path, file: r.file, mode: rmode, curves: r.curves,
                       traces: r.traces, grid: r.grid, z0: r.z0 });
    T.msg("已叠加: " + r.file, true);
    load();
  });
  T.$("sp-clear-ext").onclick = () => { S.spOverlay = []; load(); };
  sel.onchange = load;
  await load();
}

/* ═══ 代理 Playground（E3/WP0.4：滑条 → 代理实时预测，诚实呈现）═══ */
async function pagePlayground() {
  const v = T.$("view-playground");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>选一个已校准 run（有 calibration 产物），拖动参数滑条实时看代理预测指标。</li>
      <li><b>诚实呈现</b>：预测来自校准样本拟合的代理模型，<b>非真值</b>——LOOCV ρ/样本量与最近样本真值对照一并列出，精算以 openEMS/HFSS 求解为准。</li>
      <li>缺省值=参数界中点；越界滑条值会被裁剪到边界并在状态行提示。</li>
      <li>下方探索器沿单轴做参数扫描切片，画后验 mean 曲线并叠加 <b>±1σ 方差带</b>（面积阴影；仅 smt 族代理有原生逐点 σ，其余如实只画 mean）。</li>`) +
    `<h2 class='page'>代理 Playground</h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b><select id='pg-run' style='max-width:460px'></select>
         <span id='pg-quality'></span></div>
       <div id='pg-sliders'></div>
       <div id='pg-note' class='muted' style='margin-top:8px'></div>
     </div>
     <div class='panel' style='margin-top:14px'><b class='title'>代理预测 vs 最近样本真值</b>
       <div id='pg-result' class='muted'>选择 run 后自动预测</div></div>
     <div class='panel' style='margin-top:14px'><b class='title'>参数扫描探索（explore：后验 mean±std）</b>
       <div class='toolbar'>扫参轴 <select id='pg-ex-axis'></select>
         点数 <select id='pg-ex-n'><option value='11'>11</option><option value='21'>21</option><option value='41' selected>41</option></select>
         指标 <select id='pg-ex-metric'></select>
         <span id='pg-ex-status' class='muted'></span></div>
       <div id='pg-ex-chart'></div>
       <div id='pg-ex-note' class='muted' style='margin-top:8px'></div></div>`;
  const d = await T.api("/api/playground/runs");
  const runs = d.runs || [];
  const sel = T.$("pg-run");
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.best_surrogate || "?")} · ρ=${r.rho == null ? "-" : (+r.rho).toFixed(3)} · ${esc(r.verdict || "-")}）</option>`).join("");
  let debounce = null;
  let lastRun = null;
  const key = (name) => name.replace(/\W/g, "_");
  const currentParams = () => {
    const out = {};
    for (const input of T.$("pg-sliders").querySelectorAll("input[type=range]"))
      out[input.dataset.param] = +input.value;
    return out;
  };
  /* ── 探索器（DP-16 U3）：单轴参数扫描切片 → 后验 mean±std 曲线 ── */
  let exDebounce = null;
  let exReady = false;
  const scheduleExplore = () => {
    clearTimeout(exDebounce);
    exDebounce = setTimeout(runExplore, 250);
  };
  const ensureExploreControls = (bounds, metrics) => {
    const ax = T.$("pg-ex-axis");
    if (exReady && ax.dataset.run === sel.value) return;
    ax.dataset.run = sel.value;
    ax.innerHTML = Object.keys(bounds).map(
      (k) => `<option value='${escAttr(k)}'>${esc(k)}</option>`).join("");
    T.$("pg-ex-metric").innerHTML = metrics.map(
      (k) => `<option value='${escAttr(k)}'>${esc(k)}</option>`).join("");
    exReady = metrics.length > 0;
  };
  const runExplore = async () => {
    if (!sel.value || !exReady) return;
    const r = await T.api("/api/playground/explore", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: sel.value,
        params: currentParams(),
        sweep: { axis: T.$("pg-ex-axis").value, n: +T.$("pg-ex-n").value },
      }),
    });
    const st = T.$("pg-ex-status");
    if (!r.ok) {
      st.innerHTML = `<span style='color:#e57373'>✗ ${esc(r.error)}</span>`;
      return;
    }
    const metrics = Object.keys(r.curves);
    const key = metrics.includes(T.$("pg-ex-metric").value)
      ? T.$("pg-ex-metric").value : metrics[0];
    const cur = r.curves[key];
    const axisName = r.sweep.axes[0];
    const xs = r.sweep.axes_values[axisName].map((v) => +(+v).toFixed(4));
    const series = [{ name: `${key} mean`, x: xs, y: cur.mean,
    color: document.body.classList.contains("light") ? "#0277bd" : "#4fc3f7" }];
    if (cur.std)
      /* 方差带（B3 批）：GP ±1σ 区间画成面积带（app.js drawEChart band 类型），
         替代旧的两条 ±1σ 虚线——带形态更可读且不占图例双行 */
      series.push(
        { name: `${key} ±1σ`, type: "band", x: xs,
        color: document.body.classList.contains("light") ? "#0277bd" : "#4fc3f7",
          lower: cur.mean.map((m, i) => m - cur.std[i]),
          upper: cur.mean.map((m, i) => m + cur.std[i]) });
    // PR-3 PlotCard 换壳：option 与迁移前等价（base 路径，含 band 系列）
    T.plotCard(T.$("pg-ex-chart"), {
      series,
      xlabel: axisName, ylabel: key, xvalue: true, height: "300px",
      exportName: "explore-sweep", exportCsv: false,
    });
    st.textContent = `engine=${r.engine} · ${r.has_variance ? "mean±1σ" : "mean（无原生 σ）"}`
      + ` · fixed=${JSON.stringify(r.sweep.fixed)}`;
    T.$("pg-ex-note").textContent = `${r.variance_note}；${r.honest_note}`;
  };
  for (const id of ["pg-ex-axis", "pg-ex-n", "pg-ex-metric"])
    T.$(id).onchange = runExplore;
  const predict = async (params) => {
    const r = await T.api("/api/playground/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: sel.value, params }),
    });
    const box = T.$("pg-result");
    if (!r.ok) {
      box.innerHTML = `<span style='color:#e57373'>✗ ${esc(r.error)}</span>`;
      return;
    }
    const q = r.quality;
    T.$("pg-quality").innerHTML =
      (q.rho == null ? "" :
        q.verdict === "PASS" ? T.badge(`ρ=${(+q.rho).toFixed(3)} PASS`, "ok")
        : T.badge(`ρ=${(+q.rho).toFixed(3)} FAIL`, "err")) +
      ` <span class='muted'>n=${esc(q.n_samples ?? "-")} · ${esc(r.kind)}</span>` +
      (r.clamped.length ? T.badge(`越界裁剪: ${r.clamped.join(", ")}`, "muted") : "");
    T.$("pg-note").textContent = r.honest_note;
    if (lastRun !== sel.value) {
      lastRun = sel.value;
      ensureExploreControls(r.bounds, Object.keys(r.predicted));
      T.$("pg-sliders").innerHTML = Object.entries(r.bounds).map(([name, b]) =>
        `<label class='muted' style='display:block;margin:10px 0 2px'>${esc(name)}
          <span id='pg-val-${key(name)}'></span>
          <input type='range' data-param='${escAttr(name)}' id='pg-s-${key(name)}'
            min='${escAttr(b[0])}' max='${escAttr(b[1])}' step='${((b[1] - b[0]) / 100).toFixed(5)}'
            value='${escAttr(r.params[name])}' style='width:100%'></label>`).join("");
      for (const input of T.$("pg-sliders").querySelectorAll("input[type=range]")) {
        const vk = "pg-val-" + key(input.dataset.param);
        T.$(vk).textContent = (+input.value).toFixed(3);
        input.oninput = () => {
          T.$(vk).textContent = (+input.value).toFixed(3);
          clearTimeout(debounce);
          debounce = setTimeout(() => predict(currentParams()), 250);
          scheduleExplore();
        };
      }
    }
    const near = r.nearest_sample.metrics || {};
    const rows = Object.entries(r.predicted).map(([k, val]) =>
      `<tr><td class='muted'>${esc(k)}</td><td><b>${esc(val)}</b></td>
       <td class='muted'>${near[k] == null ? "-" : (+near[k]).toFixed(4)}</td></tr>`).join("");
    box.innerHTML =
      `<table><thead><tr><th>指标</th><th>代理预测</th>` +
      `<th>最近样本真值（归一化距离 ${r.nearest_sample.normalized_distance}）</th></tr></thead>` +
      `<tbody>${rows}</tbody></table>`;
  };
  sel.onchange = () => { lastRun = null; predict({}); };
  if (runs.length) await predict({});
  else T.$("pg-result").textContent = "暂无有校准产物的 run（先跑校准战役）";
}

/* ═══ 成本时间线（阶段 3.4）═══ */
async function pageTimeline() {
  const v = T.$("view-timeline");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>上图：每个 run 的目标成本（快照 objectives 确定性重算，越低越好）按时间排列——战役/调参的整体进步一目了然，颜色按 adapter 分通道。</li>
      <li>下图：最近一次调参 run 的 trial 级 cost 收敛曲线（数据来自 trials 产物）。</li>
      <li>无配方快照或无指标的 run 不画点（计数见状态行）。</li>`) +
    `<h2 class='page'>成本时间线</h2>
     <div class='panel'><b>Run 目标成本时间线（低=好）</b><div id='tl-cost'></div>
       <div id='tl-info' class='muted' style='margin-top:6px'></div></div>
     <div class='panel' style='margin-top:14px'><b>调参收敛（最近 tune run）</b>
       <div id='tl-tune'></div></div>`;
  const d = await T.api("/api/cost_timeline");
  if (!d.ok) {
    T.$("tl-cost").innerHTML = `<span class='muted'>${esc((d.errors || []).join("; "))}</span>`;
    return;
  }
  const pts = d.points || [];
  const labels = pts.map((p) => p.timestamp.slice(5, 16).replace("T", " "));
  const byAdapter = {};
  pts.forEach((p) => (byAdapter[p.adapter] = byAdapter[p.adapter] || []).push(p));
  const colors = document.body.classList.contains("light")
      ? ["#0277bd", "#b26a00", "#276b2c", "#c62828", "#6a1b9a"] // 浅色白底 ≥3:1
      : ["#4fc3f7", "#ffb74d", "#81c784", "#e57373", "#ba68c8"];
  // PR-3 PlotCard 换壳：option 与迁移前等价（base 路径）
  T.plotCard(T.$("tl-cost"), {
    series: Object.keys(byAdapter).map((a, i) => ({
      name: a, x: labels,
      y: byAdapter[a].map((p) => +p.cost.toFixed(4)),
      color: colors[i % colors.length],
    })),
    xlabel: "run 时间（旧→新）", ylabel: "cost", height: "300px",
    exportName: "cost-timeline",
  });
  T.$("tl-info").textContent =
    `${pts.length} 个 run 有成本` +
    (d.n_without_cost ? ` · ${d.n_without_cost} 个无快照/指标未画` : "") +
    (pts.length ? ` · 最新 ${pts[pts.length - 1].run_id}（${pts[pts.length - 1].adapter}）` : "");
  const tr = d.latest_tune_trials || [];
  if (tr.length)
    // PR-3 PlotCard 换壳 + convergence（声明增量：best-so-far 阶梯+末点）
    T.plotCard(T.$("tl-tune"), {
      series: [{
        name: "trial cost", x: tr.map((t) => t.trial_number),
        y: tr.map((t) => t.cost),
        color: document.body.classList.contains("light") ? "#b26a00" : "#ffb74d",
      }],
      mode: "convergence",
      xvalue: true, xlabel: "trial", ylabel: "cost", height: "260px",
      exportName: "tune-trial-convergence",
      ariaLabel: "图表：trial cost，纵轴 cost，横轴 trial（含 best-so-far 阶梯）",
    });
  else
    T.$("tl-tune").innerHTML = "<span class='muted'>暂无调参 run（到「优化调参」页启动一次）</span>";
}

/* ═══ 报告中心（阶段 3.5；PR-4 深化：①TOC+scrollspy ③双 run 对比；
   ②打印面=@media print 在 index.html，浏览器"打印为 PDF"不自研）═══ */

/* PR-4 ①：报告 TOC——marked 渲染后给 h2/h3 稳定 id（slug 去重 + 序号兜底），
   >3 节出左侧栏 + scrollspy（window scroll 被动监听；nav 摘除时自清理）。 */
function buildReportToc(body) {
  const heads = [...body.querySelectorAll("h2, h3")];
  const used = new Set();
  heads.forEach((h, i) => {
    const base = "sec-" + (h.textContent || "").trim().toLowerCase()
      .replace(/[^\w\u4e00-\u9fff]+/g, "-").replace(/^-+|-+$/g, "");
    let id = base || "sec-" + i;
    let n = 2;
    while (used.has(id) || document.getElementById(id)) id = `${base}-${n++}`;
    used.add(id);
    h.id = id;
  });
  if (heads.length <= 3) return null; // 短报告不出目录（规格口径）
  const nav = document.createElement("nav");
  nav.className = "report-toc";
  nav.setAttribute("aria-label", "报告目录");
  nav.innerHTML = heads.map((h) => {
    const lvl = h.tagName === "H3" ? "toc-h3" : "toc-h2";
    return `<a href="#${escAttr(h.id)}" data-t="${escAttr(h.id)}" class="${lvl}">${esc(h.textContent || "")}</a>`;
  }).join("");
  const links = {};
  nav.querySelectorAll("a").forEach((a) => { links[a.dataset.t] = a; });
  const spy = () => {
    let cur = heads[0];
    for (const h of heads) if (h.getBoundingClientRect().top <= 120) cur = h;
    for (const h of heads) {
      const a = links[h.id];
      if (a) a.classList.toggle("active", h === cur);
    }
  };
  const onScroll = () => {
    if (!nav.isConnected) { window.removeEventListener("scroll", onScroll); return; }
    spy();
  };
  window.addEventListener("scroll", onScroll, { passive: true });
  nav.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    const h = document.getElementById(a.dataset.t);
    if (h) h.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  spy();
  return nav;
}

/* PR-4 ③：双 run 对比（只读）：GET /api/runs/diff 服务面 +
   两栏 diff 表 + 单 PlotCard 叠图；跨模型显式警示"口径不同"。 */
async function renderRunDiff() {
  const out = T.$("rd-out");
  if (!out) return;
  const a = T.$("rd-a").value, b = T.$("rd-b").value;
  if (!a || !b || a === b) { out.innerHTML = "<span class='muted'>选两个不同的 run</span>"; return; }
  out.innerHTML = "<span class='spin'></span> 对比中...";
  const d = await T.api("/api/runs/diff?a=" + encodeURIComponent(a) +
                        "&b=" + encodeURIComponent(b));
  if (!d.ok) {
    out.innerHTML = `<span style="color:var(--err)">${esc((d.errors || ["对比失败"]).join("; "))}</span>`;
    return;
  }
  const fmt = (x) => (x == null || typeof x !== "number") ? "-" : (+x).toFixed(4);
  const j = (x) => esc(JSON.stringify(x ?? null));
  const crossModel = !d.same_model || !d.same_adapter;
  const ma = d.a?.model || "?", mb = d.b?.model || "?";
  const aa = d.a?.adapter || "?", ab = d.b?.adapter || "?";
  const mrows = Object.entries(d.metrics_delta || {}).map(([k, v]) =>
    `<tr><td><b>${esc(k)}</b></td><td class="muted">${esc(fmt(v.a))}</td>` +
    `<td class="muted">${esc(fmt(v.b))}</td><td>${esc(fmt(v.delta))}</td></tr>`).join("");
  const prows = (d.params_recursive_diff || []).map((e) =>
    `<tr><td class="muted">${esc(e.path)}</td><td>${esc(e.kind)}</td>` +
    `<td class="muted">${j(e.a)}</td><td class="muted">${j(e.b)}</td></tr>`).join("");
  const hints = (d.verdict_hints || []).map((h) => `· ${esc(h)}`).join("<br>");
  let html = "";
  if (crossModel)
    html += `<div style="color:var(--warn);border:1px dashed var(--warn);border-radius:8px;padding:8px 12px;margin-bottom:10px">` +
      `⚠ 口径不同：模型 a=${esc(ma)} / b=${esc(mb)}，通道 a=${esc(aa)} / b=${esc(ab)}` +
      `——指标与曲线不可直接比较，仅作形态参考。</div>`;
  html += `<div class="muted" style="margin-bottom:8px">${hints}</div>`;
  html += `<div class="grid2"><div><b class="muted">指标 Δ（b − a）</b>` +
    `<table><thead><tr><th>指标</th><th>a</th><th>b</th><th>Δ</th></tr></thead><tbody>` +
    (mrows || "<tr><td colspan='4' class='muted'>两侧均无指标</td></tr>") +
    `</tbody></table></div>` +
    `<div><b class="muted">配方快照递归 diff（${(d.params_recursive_diff || []).length} 处）</b>` +
    `<div style="max-height:260px;overflow:auto"><table><thead><tr><th>路径</th><th>类型</th><th>a</th><th>b</th></tr></thead><tbody>` +
    (prows || "<tr><td colspan='4' class='muted'>快照无差异</td></tr>") +
    `</tbody></table></div></div></div>`;
  html += `<b class="muted">S 参数叠图（a 前 5 色蓝系 / b 橙系，dB）</b><div id='rd-chart'></div>`;
  out.innerHTML = html;
  const series = [];
  const ca = document.body.classList.contains("light") ? "#0277bd" : "#4fc3f7";
  const cb = document.body.classList.contains("light") ? "#b26a00" : "#ffb74d";
  for (const c of (d.sparams_a?.curves || []))
    series.push({ name: "a·" + (c.file || "") + "·" + c.name, x: c.freq_ghz, y: c.y, color: ca });
  for (const c of (d.sparams_b?.curves || []))
    series.push({ name: "b·" + (c.file || "") + "·" + c.name, x: c.freq_ghz, y: c.y, color: cb });
  const chartEl = T.$("rd-chart");
  if (series.length)
    T.plotCard(chartEl, {
      series, height: "340px", xlabel: "GHz", ylabel: "dB",
      crosshair: true, exportName: "run-diff-overlay",
    });
  else
    chartEl.innerHTML = "<span class='muted'>两侧均无 Touchstone 产物（fake 通道无曲线可叠）</span>";
}

async function pageReports() {
  const v = T.$("view-reports");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>汇总 runs/ 下全部人读报告：run 五要素报告（report.md）、夜间回归（sim_ci_report.md）、校准报告（calibration/report.md）。</li>
      <li>点行在右侧渲染；长报告（&gt;3 个 h2/h3 节）自动出<b>左侧目录</b>，点击跳转、滚动高亮当前节。</li>
      <li><b>双 run 对比</b>（页底）：选 A/B 两个 run 出参数递归 diff、指标 Δ 与 S 参数叠图；跨模型对比会显式警示「口径不同」。</li>
      <li>打印/存 PDF：浏览器「打印 → 另存为 PDF」，导航/工具条/按钮自动隐藏、强制白底。</li>
      <li>原文可折叠展开。报告是产物，中心只读不写。</li>`) +
    `<h2 class='page'>报告中心</h2>
     <div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>
       <div class='panel' style='flex:1;min-width:330px'><div class='toolbar'><b>报告清单</b>
         <span id='rp-count' class='muted'></span></div>
         <table id='rp-table'><thead><tr><th>run</th><th>类型</th><th>模型</th><th>大小</th></tr></thead><tbody></tbody></table></div>
       <div class='panel' style='flex:1.4;min-width:420px'><div class='toolbar'><b id='rp-title'>选择左侧报告查看</b></div>
         <div id='rp-view' class='muted'>—</div></div>
     </div>
     <div class='panel' style='margin-top:14px'><b class='title'>双 run 对比（只读 diff + S 参数叠图）</b>
       <div class='toolbar'>A: <select id='rd-a' style='max-width:320px'></select>
         B: <select id='rd-b' style='max-width:320px'></select>
         <button class='act' id='rd-go'>对比</button>
         <span id='rd-info' class='muted'></span></div>
       <div id='rd-out' class='muted'>选择两个 run 后点「对比」</div></div>`;
  const d = await T.api("/api/reports");
  const list = d.reports || [];
  T.$("rp-count").textContent = `${list.length} 份`;
  const kindBadge = (k) => k === "sim_ci" ? T.badge("夜间回归", "warn")
    : k === "calibration" ? T.badge("校准", "ok") : T.badge("run 报告", "muted");
  const tbody = T.$("rp-table").querySelector("tbody");
  tbody.innerHTML = list.map((r) =>
    `<tr data-p='${escAttr(r.path)}' style='cursor:pointer'><td class='muted'>${esc(r.run_id)}</td>
     <td>${kindBadge(r.kind)}</td><td>${esc(r.model || "-")}</td>
     <td class='muted'>${(r.size_bytes / 1024).toFixed(1)} KB</td></tr>`).join("")
    || "<tr><td colspan='4' class='muted'>暂无报告</td></tr>";
  for (const tr of tbody.querySelectorAll("tr"))
    tr.onclick = async () => {
      const c = await T.api("/api/reports/content?path=" + encodeURIComponent(tr.dataset.p));
      const view = T.$("rp-view");
      if (!c.ok) { view.textContent = (c.errors || []).join("; "); return; }
      T.$("rp-title").textContent = c.path;
      const body = document.createElement("div");
      body.className = "report-body";
      // D-05：净化器不可用 → esc() 转义纯文本分支（内容永不作为 HTML 解释，
      // 与 textContent 兜底同保证；模板拼接语境用 esc 单点，见 mdReady 注）
      body.innerHTML = window.marked && mdReady()
        ? mdSanitize(window.marked.parse(c.content))
        : `<pre>${esc(c.content)}</pre>`;
      // 图片相对引用重写（项 2 裂图修复）：report.md 里 results/figs/x.png
      // 相对页面 URL 会 404，改指向白名单路由 /api/runs/<run_id>/figs/...；
      // 图缺失（404）时显示"该 run 无此图"占位而非裂图。
      const rid = c.run_id
        || ((String(tr.dataset.p).replace(/\\/g, "/").match(/runs\/([^/]+)\//) || [])[1]) || "";
      body.querySelectorAll("img").forEach((img) => {
        const src = (img.getAttribute("src") || "").replace(/\\/g, "/");
        if (!src || /^(https?:|data:|\/)/i.test(src)) return;
        img.src = "/api/runs/" + encodeURIComponent(rid) + "/figs/" + src;
        img.onerror = () => {
          const ph = document.createElement("div");
          ph.className = "muted";
          ph.style.cssText = "border:1px dashed var(--border);border-radius:6px;padding:8px;margin:6px 0";
          ph.textContent = `该 run 无此图：${src}（未生成或已清理）`;
          img.replaceWith(ph);
        };
      });
      view.innerHTML = "";
      view.style.display = "flex";
      view.style.gap = "14px";
      view.appendChild(body);
      // PR-4 ①：TOC（>3 节出左侧栏 + scrollspy；短报告保持单栏）
      const toc = buildReportToc(body);
      if (!toc) view.style.display = "";
      else view.prepend(toc);
    };
  // PR-4 ③：双 run 对比面板（run 清单 + 触发）
  const rd = await T.api("/api/runs?limit=200");
  const runList = rd.runs || [];
  const opts = runList.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.model || "?")} · ${esc(r.adapter || "?")}）</option>`).join("");
  T.$("rd-a").innerHTML = opts;
  T.$("rd-b").innerHTML = opts;
  if (S.currentRunId && runList.some((r) => r.run_id === S.currentRunId))
    T.$("rd-a").value = S.currentRunId;
  T.$("rd-go").onclick = () => renderRunDiff();
}

/* ── 执行看板（WP3.5 v1.2 增强②）：自治环步骤可视 + 暂停/接管 ────────────
   CLI 批处理 + GUI 观察的折中路线：环进程写 runs/loop_boards/<id>.json，
   本页只读看板 + 下发控制命令（环在步骤边界协作式响应，不打断仿真）。 */

let loopTimer = null;
let loopSelected = null;

async function pageLoopBoard() {
  const v = T.$("view-loopboard");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>自验证环（propose→verify→fix + 由易到难里程碑）以批处理方式在 service 层跑，本页<b>观察</b>当前步骤与逐里程碑验收，并可下发 <b>暂停/继续/接管</b>。</li>
      <li>暂停是<b>协作式</b>的：环只在步骤边界响应，不打断进行中的仿真；暂停超时自动续跑（批处理不被无限期挂死）。</li>
      <li><b>接管</b>：环如实停止（verdict=TAKEN_OVER），best-so-far 参数已落沙箱草稿，去「Agent 助手」promote 走三层 Gate 继续生效。</li>`) +
    `<h2 class='page'>执行看板 <small>自治环步骤可视 + 暂停/接管（CLI 批处理 + GUI 观察）</small></h2>
      <div class='panel'><div class='toolbar'>
        看板: <select id='lb-id' style='min-width:300px'></select>
        <button class='minor' id='lb-refresh'>刷新清单</button>
        <span id='lb-status'></span>
      </div>
      <div id='lb-current' class='muted' style='margin-top:6px'></div></div>
      <div class='panel'><b class='title'>里程碑（由易到难，逐项验收）</b>
        <table id='lb-ms'><thead><tr><th>ID</th><th>里程碑</th><th>难度</th><th>验收判据</th><th>状态</th></tr></thead><tbody></tbody></table></div>
      <div class='panel'><b class='title'>控制（环在步骤边界响应）</b>
        <div class='toolbar'>
          <button class='act' id='lb-pause'>⏸ 暂停</button>
          <button class='minor' id='lb-resume'>▶ 继续</button>
          <button class='minor' id='lb-takeover'>✋ 接管</button>
        </div>
        <div id='lb-best' class='muted' style='margin-top:6px'></div></div>
      <div class='panel'><b class='title'>步骤历史</b>
        <table id='lb-steps'><thead><tr><th>#</th><th>步骤</th><th>里程碑</th><th>详情</th><th>时间</th></tr></thead><tbody></tbody></table></div>`;
  T.$("lb-refresh").onclick = loadBoards;
  T.$("lb-id").onchange = () => { loopSelected = T.$("lb-id").value || null; pollBoard(); };
  T.$("lb-pause").onclick = () => sendControl("pause");
  T.$("lb-resume").onclick = () => sendControl("resume");
  T.$("lb-takeover").onclick = () => sendControl("takeover");
  clearInterval(loopTimer);
  loopTimer = setInterval(pollBoard, 2000);
  await loadBoards();
  pollBoard();

  function boardBadge(s) {
    const cls = ({ passed: "ok", done: "ok", running: "muted", paused: "warn",
                   pause_requested: "warn", failed: "err", taken_over: "err" })[s]
      || "muted";
    return T.badge(s || "N/A", cls);
  }

  async function loadBoards() {
    const d = await T.api("/api/loop/boards");
    const sel = T.$("lb-id");
    const cur = loopSelected;
    sel.innerHTML = (d.boards || []).map((b) =>
      `<option value="${escAttr(b.board_id)}">${esc(b.board_id)} · ${esc(b.status || "?")} · ${esc(b.recipe || "")}</option>`).join("")
      || "<option value=''>（暂无看板——跑自治环后出现）</option>";
    if (cur && [...sel.options].some((o) => o.value === cur)) sel.value = cur;
    loopSelected = sel.value || null;
  }

  async function sendControl(action) {
    if (!loopSelected) return T.msg("先选择看板", false);
    const r = await T.api("/api/loop/control", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board_id: loopSelected, action }),
    });
    T.msg(r.ok ? `已下发 ${action}，环在步骤边界响应` : (r.error || "命令失败"),
      !!r.ok);
    pollBoard();
  }

  async function pollBoard() {
    if (!T.$("view-loopboard") || T.$("view-loopboard").style.display === "none")
      return;
    if (!loopSelected) return;
    const b = await T.api("/api/loop/board/" + encodeURIComponent(loopSelected));
    if (!b.ok) { T.$("lb-status").textContent = b.error || ""; return; }
    T.$("lb-status").innerHTML = boardBadge(b.status);
    const cs = b.current_step;
    T.$("lb-current").innerHTML = cs
      ? `当前步骤：<b>${esc(cs.name)}</b>${cs.milestone ? "（" + esc(cs.milestone) + "）" : ""} · ${esc(cs.detail || "")} · ${esc(cs.at || "")}`
      : `配方：${esc(b.recipe || "?")} · 步骤空闲 · 更新于 ${esc(b.updated_at || "")}`;
    const ms = T.$("lb-ms").querySelector("tbody");
    ms.innerHTML = (b.milestones || []).map((m) =>
      `<tr><td>${esc(m.id)}</td><td>${esc(m.name)}</td><td class='muted'>${esc(m.difficulty)}</td>
       <td class='muted'>${esc(m.acceptance)}${m.detail ? "<br>→ " + esc(m.detail) : ""}</td>
       <td>${boardBadge(m.status)}</td></tr>`).join("")
      || "<tr><td colspan='5' class='muted'>无里程碑</td></tr>";
    T.$("lb-best").innerHTML = b.best
      ? `best cost=<b>${(b.best.cost ?? 0).toFixed(4)}</b> · 参数 <code>${esc(JSON.stringify(b.best.params || {}))}</code>`
      : esc(b.summary || "尚无有效评估点");
    const st = T.$("lb-steps").querySelector("tbody");
    st.innerHTML = (b.steps || []).slice(-12).reverse().map((s) =>
      `<tr><td>${esc(s.index)}</td><td>${esc(s.name)}</td><td>${esc(s.milestone || "")}</td>
       <td class='muted'>${s.result ? esc(JSON.stringify(s.result).slice(0, 120)) : esc(s.detail || "")}</td>
       <td class='muted'>${esc(s.at || "")}</td></tr>`).join("")
      || "<tr><td colspan='5' class='muted'>暂无完成步骤</td></tr>";
  }
}

/* ── 远场极坐标页（WP4.1/D4：nf2ff 方向图 + 增益/效率/SAR）───────────── */
async function pageFarfield() {
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
    box.innerHTML = (d.cuts || []).map((c, i) =>
      `<div style='margin-bottom:8px'><b class='muted'>φ=${c.phi_deg}° 切面` +
      `（HPBW ${c.hpbw_deg === null ? "N/A" : c.hpbw_deg.toFixed(1) + "°"} · ` +
      `F/B ${c.front_to_back_db === null ? "N/A" : c.front_to_back_db.toFixed(1) + " dB"}）</b>` +
      `<div id='ff-pol-${i}'></div></div>`).join("");
    (d.cuts || []).forEach((c, i) => {
      try {
        const light = document.body.classList.contains("light");
        const fg = light ? "#1b2330" : "#dce3ee";
        const el = T.$(`ff-pol-${i}`);
        el.style.height = "360px";
        const chart = window.echarts.init(el);
        chart.setOption({
          backgroundColor: "transparent",
          tooltip: {},
          angleAxis: {
            type: "value", min: -180, max: 180, startAngle: 90,
            axisLine: { lineStyle: { color: "#55607a" } },
            axisLabel: { color: fg }, splitLine: { show: true },
          },
          radiusAxis: {
            min: -40, max: 0,
            axisLine: { lineStyle: { color: "#55607a" } },
            axisLabel: { color: fg }, splitLine: { show: true },
          },
          polar: {},
          series: [{
            type: "line", coordinateSystem: "polar", showSymbol: false,
            data: c.theta_deg.map((t, j) => [c.pattern_db[j], t]),
            lineStyle: { width: 1.8, color: document.body.classList.contains("light")
              ? "#0277bd" : "#4fc3f7" },
          }],
        });
        window.addEventListener("resize", () => chart.resize());
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
function drawSmith(el, traces, grid, z0) {
  try {
    const light = document.body.classList.contains("light");
    const fg = light ? "#1b2330" : "#dce3ee";
    const gridColor = light ? "#b8c2d2" : "#3a4458";
    const size = Math.min(el.clientWidth || 560, 560);
    el.innerHTML = "";
    el.style.height = `${size}px`;
    el.style.width = `${size}px`;
    const chart = window.echarts.init(el);
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
    const colors = light
      ? ["#0277bd", "#b26a00", "#276b2c", "#c62828", "#6a1b9a", "#0e8f74"] // 浅色：白底 ≥3:1
      : ["#4fc3f7", "#ffb74d", "#81c784", "#e57373", "#ba68c8", "#fff176"];
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
    });
    // PR-1 a11y：图表容器图像语义（轨迹名 + Z0 进 aria-label，读屏可闻）
    el.setAttribute("role", "img");
    el.setAttribute("aria-label",
      `Smith 圆图：${(traces.map((t) => t.label || t.name)).join("、") || "无轨迹"}（Z0=${z0 ?? 50}Ω）`);
    const note = document.createElement("div");
    note.className = "muted";
    note.style.marginTop = "4px";
    note.textContent = `Z0 = ${z0 ?? 50} Ω · 网格 r=${(grid ? grid.r_circles.map((c) => c.r) : []).join("/")}、±x 同档 · 轨迹点 = 各频点 Γ（起点=首频）`;
    el.parentElement.appendChild(note);
    window.addEventListener("resize", () => chart.resize());
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
    const light = document.body.classList.contains("light");
    const fg = light ? "#1b2330" : "#dce3ee";
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
    el.innerHTML = "";
    el.style.height = "300px";
    const chart = window.echarts.init(el);
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
    const levelColors = ["#ffffff", "#ffeb3b", "#ff5722"];
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
                   inRange: { color: ["#0d1118", "#1e3a8a", "#2563eb", "#22c55e", "#facc15", "#ef4444", "#ffffff"] } },
      series,
    });
    window.addEventListener("resize", () => chart.resize());
    return chart;
  } catch (e) {
    el.innerHTML = `<span style="color:var(--err)">slice error: ${esc(e.message)}</span>`;
    return null;
  }
}

/* PyVista 等值面三角网 → three.js（顶点按 dB 着色；无 PyVista 时服务层不给此块） */
function drawIsoMesh(container, iso) {
  const THREE = T.THREE;
  container.innerHTML = "";
  const w = container.clientWidth || 600, h = 380;
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(w, h);
  container.appendChild(renderer.domElement);
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
    const light = document.body.classList.contains("light");
    const fg = light ? "#1b2330" : "#dce3ee";
    const data = [];
    p.db.forEach((row, ti) => row.forEach((v, pi) => data.push([pi, ti, v])));
    el.innerHTML = "";
    el.style.height = "300px";
    const chart = window.echarts.init(el);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { formatter: (q) => `θ=${p.theta_deg[q.value[1]]}° φ=${p.phi_deg[q.value[0]]}°<br>${q.value[2].toFixed(2)} dB` },
      grid: { left: 52, right: 70, top: 10, bottom: 34 },
      xAxis: { type: "category", data: p.phi_deg, name: "φ (deg)", nameTextStyle: { color: fg }, axisLabel: { color: fg } },
      yAxis: { type: "category", data: p.theta_deg, name: "θ (deg)", nameTextStyle: { color: fg }, axisLabel: { color: fg } },
      visualMap: { type: "continuous", min: -40, max: 0, right: 4, top: "middle", calculable: true,
                   textStyle: { color: fg },
                   inRange: { color: ["#0d1118", "#1e3a8a", "#2563eb", "#22c55e", "#facc15", "#ef4444", "#ffffff"] } },
      series: [{ type: "heatmap", data, animation: false, progressive: 2000 }],
    });
    window.addEventListener("resize", () => chart.resize());
  } catch (e) {
    el.innerHTML = `<span style="color:var(--err)">pattern error: ${esc(e.message)}</span>`;
  }
}

async function pageField() {
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
    box.innerHTML = d.slices.map((s) =>
      `<div style='margin-bottom:8px'><b class='muted'>${esc(s.axis)} = ${esc(s.position_mm)} mm 切面（${esc(s.u_axis)}×${esc(s.v_axis)}，索引 ${esc(s.index)}/${esc(s.n - 1)}）</b>
         <input type='range' min='0' max='${escAttr(s.n - 1)}' value='${escAttr(s.index)}' data-ax='${escAttr(s.axis)}' style='width:220px;vertical-align:middle'>
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

/* ═══ 优化洞察（E9 Pareto 前沿 / E10 可行性热图）═══
   数据解释全在 service（ui_service.pareto_view / feasibility_heatmap）；
   前端只渲染：前沿散点（echarts）+ 可行率网格（canvas，复用场页热图的
   单元格按真实坐标绘制画法，无新前端依赖）。 */
function drawFeasibilityGrid(el, d) {
  el.innerHTML = "";
  const light = document.body.classList.contains("light");
  const fg = light ? "#1b2330" : "#dce3ee";
  const canvas = document.createElement("canvas");
  canvas.style.width = "100%"; canvas.style.height = "340px";
  el.appendChild(canvas);
  const info = document.createElement("div");
  info.className = "muted"; info.style.marginTop = "6px";
  el.appendChild(info);
  const W = canvas.width = canvas.clientWidth || 700, H = canvas.height = 340;
  const L = 60, R = 90, Tp = 12, B = 40;
  const ctx = canvas.getContext("2d");
  const xe = d.x_edges, ye = d.y_edges, n = d.grid_n;
  const xmin = xe[0], xmax = xe[xe.length - 1], ymin = ye[0], ymax = ye[ye.length - 1];
  const px = (x) => L + ((x - xmin) / (xmax - xmin || 1)) * (W - L - R);
  const py = (y) => H - B - ((y - ymin) / (ymax - ymin || 1)) * (H - Tp - B);
  // 可行率色标：红（0）→ 黄（0.5）→ 绿（1）；空格灰
  const color = (r) => {
    if (r === null || r === undefined) return light ? "#e5e9f0" : "#1a2130";
    const g = Math.round(r <= 0.5 ? 80 + 300 * r : 230), rr = Math.round(r <= 0.5 ? 235 : 235 - 350 * (r - 0.5));
    return `rgb(${Math.max(0, Math.min(235, rr))},${Math.max(0, Math.min(230, g))},70)`;
  };
  const byCell = {};
  for (const c of d.cells) byCell[`${c.i},${c.j}`] = c;
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++) {
      const c = byCell[`${i},${j}`];
      ctx.fillStyle = color(c ? c.feasible_rate : null);
      const x0 = px(xe[i]), x1 = px(xe[i + 1]), y0 = py(ye[j + 1]), y1 = py(ye[j]);
      ctx.fillRect(x0, y0, Math.max(1, x1 - x0 - 0.5), Math.max(1, y1 - y0 - 0.5));
      if (c) {
        ctx.fillStyle = fg; ctx.font = "10px sans-serif"; ctx.textAlign = "center";
        ctx.fillText(String(c.n), (x0 + x1) / 2, (y0 + y1) / 2 + 3);
      }
    }
  // 轴与色标
  ctx.fillStyle = fg; ctx.font = "11px sans-serif"; ctx.textAlign = "center";
  ctx.fillText(`${d.x_param}  [${xmin.toPrecision(4)} … ${xmax.toPrecision(4)}]`, (L + W - R) / 2, H - 10);
  ctx.save(); ctx.translate(14, (Tp + H - B) / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText(`${d.y_param}  [${ymin.toPrecision(4)} … ${ymax.toPrecision(4)}]`, 0, 0); ctx.restore();
  const cx = W - R + 20, ch = H - Tp - B;
  for (let k = 0; k < ch; k++) {
    ctx.fillStyle = color(1 - k / ch);
    ctx.fillRect(cx, Tp + k, 14, 1);
  }
  ctx.fillStyle = fg; ctx.textAlign = "left";
  ctx.fillText("可行率 1", cx + 18, Tp + 10);
  ctx.fillText("0", cx + 18, Tp + ch);
  info.textContent = `${d.n_trials_used}/${d.n_trials_total} 条 trial 参与分箱 · 可行 ${d.n_feasible_total} · ` +
    `${d.cells.length}/${n * n} 格有样本（格内数字=样本数；灰=无样本）`;
  canvas.onmousemove = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const mx = (ev.clientX - rect.left) * (W / rect.width), my = (ev.clientY - rect.top) * (H / rect.height);
    const xv = xmin + ((mx - L) / (W - L - R)) * (xmax - xmin);
    const yv = ymin + ((H - B - my) / (H - Tp - B)) * (ymax - ymin);
    const i = Math.min(n - 1, Math.max(0, Math.floor(((xv - xmin) / (xmax - xmin || 1)) * n)));
    const j = Math.min(n - 1, Math.max(0, Math.floor(((yv - ymin) / (ymax - ymin || 1)) * n)));
    const c = byCell[`${i},${j}`];
    canvas.title = c
      ? `${d.x_param}∈[${xe[i].toPrecision(4)},${xe[i + 1].toPrecision(4)}] ${d.y_param}∈[${ye[j].toPrecision(4)},${ye[j + 1].toPrecision(4)}]\n` +
        `n=${c.n} 可行 ${c.n_feasible} 可行率 ${(c.feasible_rate * 100).toFixed(0)}% 平均总违约 ${c.mean_total_violation.toFixed(4)}`
      : "（无样本）";
  };
}

async function pageOptStack() {
  const v = T.$("view-optstack");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>Pareto 前沿：nsga2 run 直读 results/pareto_front.json（E9 起落盘，含逐代精英存档超体积 hv_convergence）；旧 run / TPE run 由服务层从 trials 审计现算约束 Pareto（Deb 可行优先支配：可行支配不可行、不可行间总违约量小者优）。</li>
      <li>可行性热图：读 trials/*.json 的 params + constraint_values（≤0=可行），对所选两参数做确定性等宽分箱——格色=可行率、格内数字=样本数、悬停看平均总违约量；无约束 run 如实报"不可算"。</li>
      <li>数值全部出自确定性内核（SpecEvaluator 违约量 / pareto_tools），前端只渲染。</li>`) +
    `<h2 class='page'>优化洞察<small>Pareto 前沿 · 可行性热图（E9/E10）</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b>
         <select id='os-run' style='max-width:340px'></select>
         <button class='minor' id='os-reload'>刷新</button>
         <span id='os-src' class='muted'></span></div>
       <div id='os-pareto'></div>
       <div id='os-hv' class='muted' style='margin-top:6px'></div>
     </div>
     <div class='panel'>
       <div class='toolbar'><b>x 参数</b><select id='os-x' style='max-width:200px'></select>
         <b>y 参数</b><select id='os-y' style='max-width:200px'></select>
         <b>网格</b><input id='os-n' value='12' style='width:56px'>
         <button class='minor' id='os-heat-btn'>可行性热图</button>
         <span id='os-info' class='muted'></span></div>
       <div id='os-heat'></div>
     </div>`;
  const listing = await T.api("/api/pareto_runs");
  const runs = listing.runs || [];
  const sel = T.$("os-run");
  if (!runs.length) {
    sel.innerHTML = "<option>（无 run）</option>";
    T.$("os-src").textContent = "先跑一次 tune --multi（nsga2）或带 optimization.constraints 的 tune";
    return;
  }
  // 分组下拉（项 3）：优化 run 排前，单点仿真 run 标注排后（仍可选，选中给人话空态）
  const tierLabel = { front: "有 Pareto 前沿（pareto_front.json）",
                      trials: "有调参轨迹（可由 trials 现算前沿）",
                      single: "单点仿真（无优化轨迹）" };
  const tierClass = { front: "", trials: "", single: "muted" };
  const byTier = { front: [], trials: [], single: [] };
  for (const r of runs) (byTier[r.tier] = byTier[r.tier] || []).push(r);
  sel.innerHTML = ["front", "trials", "single"]
    .filter((t) => byTier[t].length)
    .map((t) => `<optgroup label='${escAttr(tierLabel[t])}'>` + byTier[t].map((r) =>
      `<option value='${escAttr(r.run_id)}' class='${tierClass[t]}'>${esc(r.run_id)}（${esc(r.model || r.adapter || "?")}${t === "trials" ? " · " + esc(r.n_trials) + " trials" : ""}${t === "single" ? " · 单点" : ""}）</option>`).join("") + "</optgroup>")
    .join("");
  if (S.osRunId && runs.some((r) => r.run_id === S.osRunId)) sel.value = S.osRunId;

  const fillParams = (names) => {
    const opts = names.map((n) => `<option value='${escAttr(n)}'>${esc(n)}</option>`).join("")
      || "<option value=''>（先选一个优化 run）</option>";
    T.$("os-x").innerHTML = opts; T.$("os-y").innerHTML = opts;
    if (names.length > 1) T.$("os-y").value = names[1];
  };

  async function loadPareto() {
    S.osRunId = sel.value;
    const d = await T.api(`/api/runs/${encodeURIComponent(sel.value)}/pareto`);
    const el = T.$("os-pareto"), hv = T.$("os-hv");
    hv.textContent = "";
    if (!d.ok) {
      // 人话空态（项 3）：单点仿真 run 没有优化轨迹是预期，不是故障
      const meta = runs.find((r) => r.run_id === sel.value) || {};
      const human = meta.tier === "single"
        ? "该 run 是单点仿真，没有优化轨迹——请在下拉里选择带 pareto_front.json 的优化 run（或带 trials 的调参 run，可由 trials 现算前沿）。"
        : "该 run 暂无可画的 Pareto 前沿。";
      el.innerHTML = `<div class='muted'>${human}<br><small>${esc((d.errors || []).join("; "))}</small></div>`;
      T.$("os-src").textContent = "";
      fillParams([]);
      return;
    }
    fillParams(d.param_names || []);
    const names = d.objective_names || [];
    const pts = d.points || [];
    T.$("os-src").textContent = `来源 ${d.source} · ${d.n_pareto} 点` +
      (d.constraint_names && d.constraint_names.length ? ` · 约束 ${d.constraint_names.join(",")}` : "");
    if (!pts.length || names.length < 2) {
      el.innerHTML = "<div class='muted'>前沿为空或目标数不足 2</div>";
      return;
    }
    const feas = pts.filter((p) => p.feasible !== false);
    const infeas = pts.filter((p) => p.feasible === false);
    const toXY = (p) => [+p.objectives[names[0]], +p.objectives[names[1]]];
    const series = [{ name: `前沿${infeas.length ? "（可行）" : ""}`, type: "scatter",
                      data: feas.map(toXY),
                      color: document.body.classList.contains("light") ? "#0e8f74" : "#22d3a5",
                      symbolSize: 11 }];
    if (infeas.length)
      series.push({ name: "不可行", type: "scatter", data: infeas.map(toXY),
        color: document.body.classList.contains("light") ? "#b3261e" : "#ef5350", symbolSize: 9 });
    // PR-3 PlotCard 换壳：option 与迁移前等价（scatter+xvalue，zoom off）
    T.plotCard(el, {
      series,
      xvalue: true, xlabel: `${names[0]} 违约量`, ylabel: `${names[1]} 违约量`,
      height: "300px", zoom: false,
      exportName: "pareto-front", exportCsv: false,
    });
    if (names.length > 2)
      hv.textContent = `目标 ${names.length} 维，散点取前两维（${names.slice(2).join(", ")} 未画）。`;
    if (d.hv_convergence && d.hv_convergence.length) {
      const h = d.hv_convergence;
      const mono = h.every((x, i) => i === 0 || x >= h[i - 1] - 1e-12);
      hv.textContent += ` 超体积收敛：${h.length} 代，${h[0].toFixed(4)} → ${h[h.length - 1].toFixed(4)}` +
        `（精英存档${mono ? "弱单调 ✓" : "非单调 ✗"}）`;
    }
  }

  async function loadHeat() {
    const x = T.$("os-x").value, y = T.$("os-y").value;
    const q = new URLSearchParams({ x_param: x, y_param: y, grid_n: T.$("os-n").value || "12" });
    const d = await T.api(`/api/runs/${encodeURIComponent(sel.value)}/feasibility?${q}`);
    const info = T.$("os-info"), el = T.$("os-heat");
    if (!d.ok) { info.textContent = (d.errors || []).join("; "); el.innerHTML = ""; return; }
    info.textContent = "";
    drawFeasibilityGrid(el, d);
  }
  sel.onchange = () => { loadPareto(); T.$("os-heat").innerHTML = ""; T.$("os-info").textContent = ""; };
  T.$("os-reload").onclick = loadPareto;
  T.$("os-heat-btn").onclick = loadHeat;
  await loadPareto();
}

/* ═══ 数据集（runs/datasets 注册表：清单 + 行级预览，只读）═══ */
async function pageDatasets() {
  const v = T.$("view-datasets");
  v.innerHTML = help(`
    <li>数据集 = 多次 run 的点级数据物化（Parquet/HDF5），是调参/校准/公开集的输入资产；本页<b>只读</b>。</li>
    <li>点数据集行 → 行级预览（抽样前 N 行）。<b>n_rows 是抽样返回行数，不是全量计数</b>；全量看「点数」列。</li>
    <li>「模板族」来自 manifest 登记的 per_family_rows / ground_truth.per_model 键集；旧 manifest 未登记时如实显示"未登记"，不臆测。</li>`) +
    `<h2 class='page'>数据集 <small>runs/datasets · 只读</small></h2>
     <div class='panel'><div class='toolbar'>
       <input id='ds-filter' size='24' placeholder='按名称/模板族过滤…'>
       <select id='ds-family'><option value=''>全部模板族</option></select>
       <button class='minor' id='ds-reload'>刷新</button>
       <span id='ds-count' class='muted'></span></div>
     <div id='ds-body' class='muted'>加载中...</div></div>
     <div id='ds-preview'></div>`;
  const d = await T.api("/api/datasets");
  const body = T.$("ds-body");
  if (!d.ok) { body.innerHTML = `<span style="color:var(--err)">${esc((d.errors || []).join("; "))}</span>`; return; }
  S.dsAll = d.datasets || [];
  const families = [...new Set(S.dsAll.flatMap((x) => x.models || []))].sort();
  T.$("ds-family").innerHTML = "<option value=''>全部模板族</option>" +
    families.map((f) => `<option>${esc(f)}</option>`).join("");

  const render = () => {
    const ft = T.$("ds-filter").value.trim().toLowerCase();
    const fam = T.$("ds-family").value;
    const rows = S.dsAll.filter((x) => {
      if (ft && !(`${x.name} ${(x.models || []).join(" ")}`.toLowerCase().includes(ft))) return false;
      if (fam && !(x.models || []).includes(fam)) return false;
      return true;
    });
    T.$("ds-count").textContent = `${rows.length} / ${S.dsAll.length} 个数据集`;
    if (!rows.length) { body.innerHTML = "<span class='muted'>无匹配数据集（runs/datasets 下先物化）</span>"; return; }
    body.innerHTML = "<table><thead><tr><th>名称</th><th>点数</th><th>行数</th><th>模板族</th><th>可见性</th><th>GT 标注</th><th>HF 导出</th><th>格式</th><th>创建时间</th></tr></thead><tbody>" +
      rows.map((x) => {
        const gt = x.n_gt_rows == null ? "<span class='muted'>-</span>"
          : `${esc(x.n_gt_rows)} 行${x.gt_unlocked ? " " + T.badge("unlocked", "ok") : ""}`;
        const famTxt = (x.models || []).length ? esc(x.models.join("、"))
          : "<span class='muted'>未登记</span>";
        return `<tr class='clickable' data-n='${escAttr(x.name)}' title='${escAttr(x.dataset_dir)}'>
          <td><b>${esc(x.name)}</b></td><td>${esc(x.n_points)}</td><td>${esc(x.n_rows)}</td>
          <td class='muted'>${famTxt}</td>
          <td>${x.visibility === "public" ? T.badge("public", "ok") : T.badge("private", "muted")}</td>
          <td class='muted'>${gt}</td>
          <td>${x.has_hf ? T.badge("有", "ok") : "<span class='muted'>无</span>"}</td>
          <td class='muted'>${esc(x.format)}</td>
          <td class='muted'>${esc((x.created_at || "").slice(0, 19).replace("T", " "))}</td></tr>`;
      }).join("") + "</tbody></table>" +
      `<div class='muted' style='margin-top:6px;font-size:11.5px'>点数据集行进入行级预览；目录：${escAttr(d.out_dir)}</div>`;
    body.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.onclick = () => loadPreview(tr.dataset.n);
    });
  };
  T.$("ds-filter").oninput = render;
  T.$("ds-family").onchange = render;
  T.$("ds-reload").onclick = () => pageDatasets();
  render();

  async function loadPreview(name) {
    const model = T.$("ds-family").value || "";
    const q = model ? `&model=${encodeURIComponent(model)}` : "";
    const p = await T.api(`/api/datasets/${encodeURIComponent(name)}/preview?limit=20${q}`);
    const el = T.$("ds-preview");
    if (!p.ok) { el.innerHTML = `<div class='panel'><b class='title'>预览 — ${escAttr(name)}</b><span style="color:var(--err)">${esc((p.errors || []).join("; "))}</span></div>`; return; }
    const cols = p.columns || [];
    const fmtCell = (val) => {
      if (val == null) return "<span class='muted'>-</span>";
      if (typeof val === "number") return String(+val.toFixed(6));
      if (typeof val === "object") return `<code>${esc(JSON.stringify(val))}</code>`;
      return esc(String(val));
    };
    el.innerHTML = `<div class='panel'><b class='title'>行级预览 — ${esc(p.dataset)}（${p.filters?.model ? `模板族 ${esc(p.filters.model)} · ` : ""}抽样 ${esc(p.n_rows)} 行；n_rows 为抽样返回行数，非全量计数）</b>
      <div style='overflow:auto;max-height:420px'><table><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>
      ${(p.rows || []).map((r) => `<tr>${cols.map((c) => `<td>${fmtCell(r[c])}</td>`).join("")}</tr>`).join("")}
      </tbody></table></div></div>`;
  }
}

/* ═══ 标定锚（锚注册表 + 新鲜度，只读）═══ */
async function pageAnchors() {
  const v = T.$("view-anchors");
  v.innerHTML = help(`
    <li>锚 = (模板族 × 引擎对 × 域) → (常量|曲线|公式|指针) 的物理标定单源（knowledge/anchors.yaml），运行时只读；修订不改历史，新证据登记 -vN+1。指针锚=双引擎分歧双值登记（不产常数、不就地求值）。</li>
    <li><b>状态</b>即注册表裁决：active 健在 / stale 已过期 / experimental 实验指针（双值分歧待归因） / awaiting_data 骨架待回填 / retired 退役。无 last_verified 的锚新鲜度如实显示 UNKNOWN（不虚构判定）。</li>
    <li>点锚行看全量记录（provenance / uncertainty / consumers）。</li>`) +
    `<h2 class='page'>标定锚 <small>物理标定锚注册表 · 只读</small></h2>
     <div class='panel'><div class='toolbar'>
       <span id='an-kpi' class='muted'>加载中...</span>
       <button class='minor' id='an-reload'>刷新</button></div>
     <div id='an-body'></div></div>
     <div id='an-detail'></div>`;
  const load = async () => {
    const d = await T.api("/api/anchors");
    const body = T.$("an-body");
    if (!d.ok) { body.innerHTML = `<span style="color:var(--err)">${esc((d.errors || []).join("; "))}</span>`; return; }
    T.$("an-kpi").innerHTML =
      `共 <b>${d.count}</b>/${d.expected_count} 锚 · ` +
      (d.stale_count ? T.badge(`${d.stale_count} stale`, "warn") : T.badge("0 stale", "ok")) + " " +
      (d.no_date_count ? T.badge(`${d.no_date_count} 无验证日期（UNKNOWN）`, "muted") : "");
    if (d.load_errors?.length)
      body.insertAdjacentHTML("beforeend",
        `<div style="color:var(--err);margin-bottom:8px">注册表装载告警：${esc(d.load_errors.join("; "))}</div>`);
    const stBadge = (st) => ({
      active: T.badge("active", "ok"), stale: T.badge("stale", "warn"),
      experimental: T.badge("experimental", "warn"),
      retired: T.badge("retired", "muted"),
      awaiting_data: T.badge("awaiting_data", "muted"),
    }[st] || T.badge(st || "UNKNOWN", "muted"));
    body.insertAdjacentHTML("beforeend",
      "<table><thead><tr><th>anchor_id</th><th>状态</th><th>锚类型</th><th>模板族</th><th>量 / 值</th><th>引擎对</th><th>新鲜度</th></tr></thead><tbody>" +
      (d.anchors || []).map((a) => {
        const si = a.stale_info || {};
        const fresh = si.stale === true
          ? T.badge(`stale（龄期 ${si.age_days} 天）`, "warn")
          : si.stale === false ? T.badge("新鲜", "ok")
          : T.badge("UNKNOWN（无验证日期）", "muted");
        const unit = a.quantity?.unit ? ` ${esc(a.quantity.unit)}` : "";
        return `<tr class='clickable' data-id='${escAttr(a.anchor_id)}'>
          <td><b>${esc(a.anchor_id)}</b></td><td>${stBadge(a.status)}</td><td class='muted'>${esc(a.kind)}</td>
          <td class='muted'>${esc((a.template_family || []).join("、"))}</td>
          <td>${esc(a.quantity?.name ?? "")} = <b>${esc(a.value ?? "-")}</b>${unit}</td>
          <td class='muted'>${a.engine_pair ? `${esc(a.engine_pair.calibrated)}→${esc(a.engine_pair.referee)}` : "-"}</td>
          <td>${fresh}</td></tr>`;
      }).join("") + "</tbody></table>");
    body.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.onclick = async () => {
        const det = await T.api("/api/anchors/" + encodeURIComponent(tr.dataset.id));
        T.$("an-detail").innerHTML = det.ok
          ? `<div class='panel'><b class='title'>锚详情 — ${esc(det.anchor.anchor_id)}</b><pre>${esc(JSON.stringify(det.anchor, null, 2))}</pre></div>`
          : `<div class='panel'><span style="color:var(--err)">${esc(det.error || "详情不可读")}</span></div>`;
      };
    });
  };
  T.$("an-reload").onclick = load;
  await load();
}

/* ═══ UQ 不确定度（代理蒙特卡洛良率 + 敏感性；数值只在确定性内核）═══ */
async function pageUq() {
  const v = T.$("view-uq");
  v.innerHTML = help(`
    <li>UQ = 代理蒙特卡洛公差分析：给定校准样本集 + 逐参数公差 σ，免费评估良率 / 指标分布 / 参数敏感性——不跑真机。</li>
    <li>数值全部由确定性内核（uq_service.surrogate_yield）产出，前端只渲染；<b>无样本集/无公差时如实空态，不 mock</b>。</li>
    <li>敏感性 = 单参数 ±1σ 扰动的指标响应幅值合计（|Δmetric| 求和），越大越该优先收公差。</li>`) +
    `<h2 class='page'>UQ 不确定度 <small>代理蒙特卡洛 · 良率 / 分布 / 敏感性</small></h2>
     <div class='panel'><b class='title'>① 校准样本集（runs/ 下 samples 资产，点选填入）</b>
       <div id='uq-assets' class='muted'>加载中...</div></div>
     <div class='panel'><b class='title'>② 运行（确定性内核，万点级秒回）</b>
       <div class='toolbar'>样本集: <input id='uq-path' style='flex:1;min-width:280px' placeholder='runs/xxx/calibration/samples.json'>
         代理: <select id='uq-kind'><option>poly_ridge</option><option>nn</option></select>
         抽样: <input id='uq-n' value='10000' size='7'> seed: <input id='uq-seed' value='42' size='5'>
         <button class='act' id='uq-run'>运行 UQ</button><span id='uq-spin'></span></div>
       <div id='uq-tol' class='muted' style='margin-top:6px'>选中样本集后这里列出逐参数公差 σ（留空=该参数不扰动）</div></div>
     <div id='uq-result'></div>`;
  const assets = await T.api("/api/uq/samples");
  const el = T.$("uq-assets");
  if (!assets.ok) { el.innerHTML = `<span style="color:var(--err)">${esc((assets.errors || []).join("; "))}</span>`; return; }
  if (!(assets.items || []).length) {
    el.innerHTML = "<span class='muted'>runs/ 下未发现校准样本集（samples.json 族）——先跑校准或战役，本页如实空态</span>";
  } else {
    el.innerHTML = "<table><thead><tr><th>文件</th><th>样本数</th><th>目标数</th><th>参数（bounds）</th><th>修改时间</th></tr></thead><tbody>" +
      assets.items.map((it) => {
        const n = it.parsed ? `${esc(it.n_samples)}` : "<span class='muted'>未解析（过大/损坏）</span>";
        return `<tr class='clickable' data-p='${escAttr(it.path)}'>
          <td><b>${esc(it.path)}</b></td><td>${n}</td>
          <td class='muted'>${it.parsed ? esc(it.n_objectives ?? "-") : "-"}</td>
          <td class='muted'>${esc((it.bounds_params || []).join("、")) || "-"}</td>
          <td class='muted'>${esc(new Date(it.mtime * 1000).toISOString().slice(0, 19).replace("T", " "))}</td></tr>`;
      }).join("") + "</tbody></table>" +
      (assets.truncated ? "<div class='muted' style='margin-top:4px'>清单已达上限，未全列</div>" : "");
    el.querySelectorAll("tr.clickable").forEach((tr) => {
      tr.onclick = () => pickAsset(tr.dataset.p);
    });
  }
  async function pickAsset(path) {
    T.$("uq-path").value = path;
    const item = (assets.items || []).find((x) => x.path === path);
    const params = (item && item.bounds_params) || [];
    T.$("uq-tol").innerHTML = params.length
      ? "<table><thead><tr><th>参数</th><th>容差 σ（与参数同单位）</th></tr></thead><tbody>" +
        params.map((n) => `<tr><td><b>${esc(n)}</b></td><td><input class='uq-sigma' data-p='${escAttr(n)}' size='12' step='any' placeholder='σ（留空不扰动）'></td></tr>`).join("") +
        "</tbody></table>"
      : "该样本集无 bounds 参数清单，σ 需按参数名手填内核参数（或换样本集）";
  }
  T.$("uq-run").onclick = async () => {
    const tolerances = {};
    let bad = null;
    document.querySelectorAll("#uq-tol .uq-sigma").forEach((inp) => {
      const raw = inp.value.trim();
      if (raw === "" || bad) return;
      const num = Number(raw);
      if (isNaN(num)) { bad = inp.dataset.p; return; }
      tolerances[inp.dataset.p] = num;
    });
    if (bad) return T.msg(`参数 ${bad} 的 σ 不是数值`, false);
    if (!Object.keys(tolerances).length) return T.msg("至少填一个参数公差 σ（内核要求 {param: σ} 非空）", false);
    const btn = T.$("uq-run");
    btn.disabled = true; T.$("uq-spin").innerHTML = "<span class='spin'></span>";
    const r = await T.api("/api/uq/yield", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ samples_path: T.$("uq-path").value.trim(),
                             tolerances, n: parseInt(T.$("uq-n").value) || 10000,
                             seed: parseInt(T.$("uq-seed").value) || 42,
                             kind: T.$("uq-kind").value }),
    });
    btn.disabled = false; T.$("uq-spin").innerHTML = "";
    renderUqResult(r);
  };

  function renderUqResult(r) {
    const el = T.$("uq-result");
    if (!r.ok) {
      el.innerHTML = `<div class='panel'><span style="color:var(--err)">UQ 未出结果（如实）：${esc((r.errors || ["未知错误"]).join("; "))}</span></div>`;
      return;
    }
    const yPct = (r.yield_rate * 100).toFixed(1) + "%";
    const yCls = r.yield_rate >= 0.9 ? "ok" : r.yield_rate >= 0.7 ? "warn" : "err";
    const stats = Object.entries(r.metric_stats || {});
    const deltas = r.sensitivity_violation_delta || {};
    const maxD = Math.max(...Object.values(deltas).map((x) => Math.abs(x)), 1e-12);
    el.innerHTML = `<div class='cards'>
        <div class='card'><div class='k'>良率</div><div class='v ${yCls}'>${yPct}</div></div>
        <div class='card'><div class='k'>抽样点数</div><div class='v'>${r.n_draws}</div></div>
        <div class='card'><div class='k'>代理</div><div class='v'>${esc(r.surrogate_kind)}</div></div>
        <div class='card'><div class='k'>名义点指标均值</div><div class='v'>${stats.length} 项</div></div>
      </div>
      <div class='grid2'>
        <div class='panel'><b class='title'>指标分布（蒙特卡洛）</b>
          <table><thead><tr><th>指标</th><th>mean</th><th>std</th><th>q05</th><th>q95</th></tr></thead><tbody>
          ${stats.map(([m, s]) => `<tr><td><b>${esc(m)}</b></td><td>${(+s.mean).toFixed(4)}</td><td>${(+s.std).toFixed(4)}</td><td>${(+s.q05).toFixed(4)}</td><td>${(+s.q95).toFixed(4)}</td></tr>`).join("") || "<tr><td colspan='5' class='muted'>无</td></tr>"}
          </tbody></table>
          <div class='muted' style='margin-top:6px;font-size:11.5px'>名义参数：${esc(JSON.stringify(r.nominal_params))}<br>实现：${esc(r.implementation || "-")} · 不确定度状态：${esc(r.uncertainty_status ?? "-")}</div></div>
        <div class='panel'><b class='title'>逐参数敏感性（±1σ 指标响应合计，降序）</b>
          ${(r.sensitivity_ranking || []).map((p) => {
            const dv = Math.abs(deltas[p] || 0);
            return `<div style='margin-bottom:8px'><b>${esc(p)}</b> <span class='muted'>|Δ|=${dv.toFixed(5)}</span>
              <div style='height:8px;border-radius:4px;background:var(--panel2);margin-top:3px'>
              <div style='height:8px;border-radius:4px;width:${(dv / maxD * 100).toFixed(1)}%;background:var(--accent)'></div></div></div>`;
          }).join("") || "<span class='muted'>无</span>"}
          <div class='muted' style='margin-top:6px;font-size:11.5px'>敏感性越大 = 该参数公差对指标影响越大，优先收公差或换设计中心。</div></div>
      </div>`;
    T.msg("UQ 完成（确定性内核）", true);
  }
}

/* ═══ PR-5 模板画廊（ge8b Wave B 席B2）：模板卡 + 参数滑块 → 闭式即时预览 ═══
   映射/量程解释全在 service/gallery_service（前端只渲染）；预览数值全部
   出自 /api/calculators/run 闭式纯函数（零 EM 求解）；未配预览通道的
   模板如实显示，不硬凑。 */
async function pageGallery() {
  const v = T.$("view-gallery");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>模板卡出自 TEMPLATE_META/TEMPLATE_NOMINAL（与 docs meta.yaml 同源）；<b>滑块改值 → 闭式计算器即时预览</b>（零 EM 求解）。</li>
      <li>闭式预览通道是<b>显式白名单</b>（当前 siw/slotline 线分析族）；未映射模板如实显示"未配通道"，不猜不硬凑。</li>
      <li>数值只在确定性内核（规则 7）：本页零物理数字产生，滑块初值=注册表名义参数。</li>`) +
    `<h2 class='page'>模板画廊 <small>交互卡 · 闭式即时预览（PR-5）</small></h2>
     <div class='toolbar'><input id='gal-filter' size='24' placeholder='按名称/拓扑过滤…'>
       <span id='gal-count' class='muted'></span></div>
     <div id='gal-grid' class='muted'>加载中...</div>
     <div id='gal-preview'></div>`;
  const d = await T.api("/api/gallery");
  const grid = T.$("gal-grid");
  if (!d.ok) { grid.innerHTML = `<span style="color:var(--err)">${esc((d.errors || []).join("; "))}</span>`; return; }
  S.galCards = d.cards || [];
  T.$("gal-count").textContent = `${d.n_templates} 模板 · ${d.n_previews} 配闭式预览通道`;
  const render = () => {
    const ft = T.$("gal-filter").value.trim().toLowerCase();
    const rows = S.galCards.filter((c) => !ft ||
      `${c.name} ${c.topology || ""}`.toLowerCase().includes(ft));
    grid.innerHTML = `<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(21rem,1fr));gap:10px'>` +
      rows.map((c) => `<div class='panel' style='margin:0'>
        <b>${esc(c.name)}</b> ${c.preview ? T.badge("闭式预览", "ok") : "<span class='muted' style='font-size:11px'>未配预览通道</span>"}
        ${c.f0_ghz ? `<span class='badge muted'>f0 ${esc(c.f0_ghz)} GHz</span>` : ""}
        <div class='muted' style='font-size:11.5px;margin:4px 0'>${esc(c.topology || "")}</div>
        <div class='muted' style='font-size:11px'>${esc(Object.entries(c.nominal_params || {}).map(([k, x]) => k + "=" + x).join(" · "))}</div>
        ${c.preview ? `<button class='minor' style='margin-top:6px' data-gal='${escAttr(c.name)}'>打开预览</button>` : ""}
      </div>`).join("") + `</div>`;
    for (const btn of grid.querySelectorAll("[data-gal]"))
      btn.onclick = () => openPreview(btn.getAttribute("data-gal"));
  };
  T.$("gal-filter").oninput = render;
  async function openPreview(name) {
    const c = S.galCards.find((x) => x.name === name);
    const p = c && c.preview;
    const box = T.$("gal-preview");
    if (!p) { box.innerHTML = ""; return; }
    const meta = p.slider_meta || {};
    box.innerHTML = `<div class='panel' style='margin-top:12px'>
      <b class='title'>闭式预览：${esc(c.name)} → <code>${esc(p.calculator)}</code></b>
      <div id='gal-sliders' style='margin:8px 0'></div>
      <div class='toolbar'><button class='primary' id='gal-run'>计算</button>
        <span id='gal-msg' class='muted'></span></div>
      <div id='gal-result' class='muted' style='margin-top:8px'>拖动滑块后点「计算」</div></div>`;
    const sliders = T.$("gal-sliders");
    const params = { ...p.params };
    sliders.innerHTML = (p.sliders || []).map((k) => {
      const m = meta[k] || { min: params[k] * 0.5, max: params[k] * 1.5, step: Math.abs(params[k]) / 100, initial: params[k] };
      return `<label style='display:block;margin:6px 0'><b>${esc(k)}</b> <span id='gal-v-${escAttr(k)}'>${(+m.initial).toPrecision(6)}</span>
        <input type='range' data-k='${escAttr(k)}' min='${m.min}' max='${m.max}' step='${m.step}' value='${m.initial}' style='width:100%'></label>`;
    }).join("") || "<span class='muted'>本通道无可调滑块（固定参数直算）</span>";
    for (const input of sliders.querySelectorAll("input[type=range]"))
      input.oninput = () => {
        params[input.getAttribute("data-k")] = Number(input.value);
        const show = T.$("gal-v-" + input.getAttribute("data-k"));
        if (show) show.textContent = (+input.value).toPrecision(6);
      };
    T.$("gal-run").onclick = async () => {
      T.$("gal-msg").textContent = "计算中...";
      const r = await T.api("/api/calculators/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: p.calculator, params }) });
      T.$("gal-msg").textContent = "";
      const el = T.$("gal-result");
      if (!r.ok) { el.innerHTML = `<span style='color:var(--err)'>✗ ${esc((r.error || (r.errors || []).join("; ")))}</span>`; return; }
      el.innerHTML = "<table><tbody>" + Object.entries(r.result || r)
        .filter(([k]) => k !== "ok")
        .map(([k, x]) => `<tr><td><b>${esc(k)}</b></td><td>${esc(typeof x === "object" ? JSON.stringify(x) : String(x))}</td></tr>`).join("")
        + "</tbody></table>";
    };
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  render();
}

/* ═══ PR-6 战役仪表盘（ge8b Wave B 席B2）：成本热图 + trial 虚拟列表 ═══
   热图=确定性分箱快照（service 端）；进度实时刷新走既有 SSE 流（P-1）。
   虚拟列表=窗口化渲染（只画可视行，千行 60fps 零框架）。 */
async function pageCampaign() {
  const v = T.$("view-campaign");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>战役 = 带 trials 审计的调参/优化 run；<b>座位状态表</b>按 cost 有效性三分（PASS 已评入盘 / SKIP 审计行剔除 / FAIL 端点错误态）。</li>
      <li><b>成本热图</b>对所选两参数确定性分箱（格色=平均 cost，格内数字=样本数）。</li>
      <li><b>trial 虚拟列表</b>只渲染可视窗口行（千行级滚动 60fps）；实时进度监听 SSE 流自动刷新。</li>
      <li>数值全部出自 trials 审计文件（优化器落盘），前端只渲染。</li>`) +
    `<h2 class='page'>战役仪表盘 <small>座位状态 · 成本热图 · trial 虚拟列表（PR-6）</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>Run</b><select id='cp-run' style='max-width:340px'></select>
         <b>x</b><select id='cp-x' style='max-width:170px'></select>
         <b>y</b><select id='cp-y' style='max-width:170px'></select>
         <b>网格</b><input id='cp-n' value='12' style='width:52px'>
         <button class='minor' id='cp-reload'>刷新</button>
         <span id='cp-info' class='muted'></span></div>
       <div id='cp-seats' style='margin-top:6px'></div>
       <div id='cp-heat'></div>
       <div id='cp-best' class='muted' style='margin-top:6px'></div>
     </div>
     <div class='panel' style='margin-top:12px'>
       <b class='title'>Trials <span id='cp-tmeta' class='muted' style='font-weight:normal'></span></b>
       <div id='cp-table' style='margin-top:6px'></div>
     </div>`;
  const listing = await T.api("/api/pareto_runs");
  const runs = (listing.runs || []).filter((r) => r.tier !== "single");
  const sel = T.$("cp-run");
  if (!runs.length) {
    sel.innerHTML = "<option>（无带 trials 的 run）</option>";
    T.$("cp-info").textContent = "先跑一次 tune（带 trials 审计的调参/优化 run）";
    return;
  }
  sel.innerHTML = runs.map((r) =>
    `<option value='${escAttr(r.run_id)}'>${esc(r.run_id)}（${esc(r.model || r.adapter || "?")} · ${esc(r.n_trials)} trials）</option>`).join("");
  const heatEl = T.$("cp-heat");
  async function loadDash() {
    const runId = sel.value;
    if (!runId) return;
    S.cpRunId = runId;
    const q = new URLSearchParams({ x_param: T.$("cp-x").value || "", y_param: T.$("cp-y").value || "", grid_n: T.$("cp-n").value || "12" });
    const d = await T.api(`/api/runs/${encodeURIComponent(runId)}/dashboard?${q}`);
    const seatsEl = T.$("cp-seats");
    if (!d.ok) {
      // FAIL 态也走同款真 <table>（X2 座位状态表口径：分色+错误串 esc）
      seatsEl.innerHTML = `<table><thead><tr><th>座位状态</th><th>数</th><th>语义</th></tr></thead><tbody>` +
        `<tr><td>${T.badge("FAIL", "err")}</td><td>—</td><td>${esc((d.errors || []).join("; "))}</td></tr>` +
        `</tbody></table>`;
      T.$("cp-info").textContent = "";
      heatEl.innerHTML = ""; T.$("cp-table").innerHTML = ""; T.$("cp-best").textContent = "";
      return;
    }
    const skipped = Math.max(0, (d.n_trials_total || 0) - (d.n_trials_used || 0));
    const pct = d.n_trials_total ? Math.round(100 * d.n_trials_used / d.n_trials_total) : 0;
    const bars = Math.max(0, Math.min(20, Math.round(pct / 5)));
    T.$("cp-info").textContent = `座位进度 ${"█".repeat(bars)}${"░".repeat(20 - bars)} ${pct}%（${d.n_trials_used}/${d.n_trials_total}）· 参数源=${d.params_source}`;
    // 座位状态表（X2 v1）：PASS=已评入盘（有限 cost）/ SKIP=审计行被剔除
    // （cost 非有限或参数坏，service 端如实剔除）/ FAIL=端点错误态（上方 !d.ok 分支）。
    // 全部数字经 esc 再插值（AU-4）；进度条走 textContent 天然无插值面。
    seatsEl.innerHTML = `<table><thead><tr><th>座位状态</th><th>数</th><th>语义</th></tr></thead><tbody>` +
      `<tr><td>${T.badge("PASS", "ok")}</td><td>${esc(d.n_trials_used)}</td><td class="muted">trial 已评且 cost 有限（入热图/表/best）</td></tr>` +
      `<tr><td>${T.badge("SKIP", skipped ? "warn" : "muted")}</td><td>${esc(skipped)}</td><td class="muted">审计行被剔除（cost 非有限/参数缺失，service 端如实跳过）</td></tr>` +
      `<tr><td>${T.badge("FAIL", "muted")}</td><td>0</td><td class="muted">端点错误态（本载荷 ok=true，无 FAIL；出错时整表换 FAIL 行）</td></tr>` +
      `</tbody></table>`;
    const opts = d.params_numeric.map((n) => `<option value='${escAttr(n)}'>${esc(n)}</option>`).join("");
    T.$("cp-x").innerHTML = opts; T.$("cp-y").innerHTML = opts;
    T.$("cp-x").value = d.x_param; T.$("cp-y").value = d.y_param;
    drawCostHeat(heatEl, d);
    T.$("cp-best").textContent = `最优 trial #${d.best.trial_number} cost=${d.best.cost}（${Object.entries(d.best.params).map(([k, x]) => k + "=" + (+x).toPrecision(6)).join(", ")}） · 平均 cost=${d.cost_mean}`;
    renderVirtualList(T.$("cp-table"), d.trials,
      (row) => `<td>${(+row.cost).toPrecision(8)}</td><td class='muted'>${esc(Object.entries(row.params).map(([k, x]) => k + "=" + (+x).toPrecision(6)).join(" · "))}</td>`,
      "<tr><th style='width:70px'>trial</th><th>cost</th><th>params</th></tr>");
    T.$("cp-tmeta").textContent = `${d.table_rows} 行${d.table_truncated ? "（已截断）" : ""}`;
  }
  sel.onchange = loadDash;
  T.$("cp-reload").onclick = loadDash;
  T.$("cp-x").onchange = loadDash; T.$("cp-y").onchange = loadDash; T.$("cp-n").onchange = loadDash;
  await loadDash();
}

/* 成本热图（canvas，feasibility 网格姊妹面）：格色=格内平均 cost 相对
   [cost_min, cost_max] 的位置（绿低红高）；空格灰。 */
function drawCostHeat(el, d) {
  el.innerHTML = "";
  const light = document.body.classList.contains("light");
  const fg = light ? "#1b2330" : "#dce3ee";
  const canvas = document.createElement("canvas");
  canvas.style.width = "100%"; canvas.style.height = "340px";
  el.appendChild(canvas);
  const W = canvas.width = canvas.clientWidth || 700, H = canvas.height = 340;
  const L = 60, R = 90, Tp = 12, B = 40;
  const ctx = canvas.getContext("2d");
  const xe = d.x_edges, ye = d.y_edges, n = d.grid_n;
  const xmin = xe[0], xmax = xe[xe.length - 1], ymin = ye[0], ymax = ye[ye.length - 1];
  const px = (x) => L + ((x - xmin) / (xmax - xmin || 1)) * (W - L - R);
  const py = (y) => H - B - ((y - ymin) / (ymax - ymin || 1)) * (H - Tp - B);
  const cmin = Math.min(...d.cells.map((c) => c.cost_mean));
  const cmax = Math.max(...d.cells.map((c) => c.cost_mean));
  const color = (r) => {
    if (r === null || r === undefined) return light ? "#e5e9f0" : "#1a2130";
    const rr = Math.round(80 + 155 * r), gg = Math.round(235 - 155 * r);
    return `rgb(${rr},${gg},70)`;
  };
  const byCell = {};
  for (const c of d.cells) byCell[`${c.i},${c.j}`] = c;
  for (let i = 0; i < n; i++)
    for (let j = 0; j < n; j++) {
      const c = byCell[`${i},${j}`];
      const rel = c ? (cmax > cmin ? (c.cost_mean - cmin) / (cmax - cmin) : 0) : null;
      ctx.fillStyle = color(rel);
      const x0 = px(xe[i]), x1 = px(xe[i + 1]), y0 = py(ye[j + 1]), y1 = py(ye[j]);
      ctx.fillRect(x0, y0, Math.max(1, x1 - x0 - 0.5), Math.max(1, y1 - y0 - 0.5));
      if (c) {
        ctx.fillStyle = fg; ctx.font = "10px sans-serif"; ctx.textAlign = "center";
        ctx.fillText(String(c.n), (x0 + x1) / 2, (y0 + y1) / 2 + 3);
      }
    }
  ctx.fillStyle = fg; ctx.font = "11px sans-serif"; ctx.textAlign = "center";
  ctx.fillText(`${d.x_param}  [${xmin.toPrecision(4)} … ${xmax.toPrecision(4)}]`, (L + W - R) / 2, H - 10);
  ctx.save(); ctx.translate(14, (Tp + H - B) / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText(`${d.y_param}  [${ymin.toPrecision(4)} … ${ymax.toPrecision(4)}]`, 0, 0); ctx.restore();
  const cx = W - R + 20, ch = H - Tp - B;
  for (let k = 0; k < ch; k++) {
    ctx.fillStyle = color(k / ch);
    ctx.fillRect(cx, Tp + k, 14, 1);
  }
  ctx.fillStyle = fg; ctx.textAlign = "left";
  ctx.fillText(`cost ${cmax.toPrecision(4)}`, cx + 18, Tp + 10);
  ctx.fillText(`${cmin.toPrecision(4)}`, cx + 18, Tp + ch);
  canvas.title = "格色=格内平均 cost（绿低红高），格内数字=样本数；悬停看格详情";
}

/* trial 虚拟列表：窗口化渲染（只画可视行 + 上下缓冲），行高恒定 28px。
   千行级滚动只重绘可视窗（~30 行 DOM），60fps 预算内；零框架 vanilla。
   renderRow 返回行内 <td> 串（首列 trial 号由本函数统一渲染）。 */
function renderVirtualList(el, rows, renderRow, headerHtml) {
  const ROW_H = 28, BUFFER = 8;
  const total = rows.length;
  el.innerHTML = "";
  const head = document.createElement("table");
  head.innerHTML = `<thead>${headerHtml}</thead>`;
  head.style.width = "100%";
  el.appendChild(head);
  const viewport = document.createElement("div");
  viewport.style.cssText = "overflow:auto;max-height:420px;position:relative";
  el.appendChild(viewport);
  if (!total) {
    viewport.innerHTML = "<div class='muted' style='padding:8px'>无 trial 行</div>";
    return;
  }
  const spacer = document.createElement("div");
  spacer.style.cssText = `height:${total * ROW_H}px;position:relative`;
  viewport.appendChild(spacer);
  const layer = document.createElement("table");
  layer.style.cssText = "position:absolute;left:0;top:0;width:100%;table-layout:fixed";
  spacer.appendChild(layer);
  let first = -1, last = -1;
  const paint = () => {
    const scrollTop = viewport.scrollTop;
    const visible = Math.ceil(viewport.clientHeight / ROW_H);
    const f = Math.max(0, Math.floor(scrollTop / ROW_H) - BUFFER);
    const l = Math.min(total, f + visible + 2 * BUFFER);
    if (f === first && l === last) return;
    first = f; last = l;
    const body = [];
    for (let i = f; i < l; i++) {
      // trial_number 出自 runs/ trials 审计（#320 导入面外来数据可达）——
      // 与行内 renderRow 同 AU-4 口径一律 esc（X2 补：此前裸插值是 XSS 面）
      body.push(`<tr style='height:${ROW_H}px'><td class='muted'>${esc(rows[i].trial_number)}</td>${renderRow(rows[i])}</tr>`);
    }
    layer.innerHTML = `<tbody>${body.join("")}</tbody>`;
  };
  viewport.onscroll = paint;
  paint();
}

/* ═══ PR-8 剖析入口（ge8b Wave B 席B2）：py-spy 火焰图落 runs/ ═══
   py-spy 为可选依赖：未装=状态卡如实"未安装"+安装提示（不假装可用）。 */
async function pageProfile() {
  const v = T.$("view-profile");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>封装 <code>py-spy record</code>（MIT）：对运行中进程（pid）或新起命令采样，产物落 runs/profile/（flamegraph .svg 浏览器直接看 / speedscope .json 可交互）。</li>
      <li>py-spy 缺装时本页如实降级：<code>pip install py-spy</code> 后刷新即可。</li>
      <li>剖析是开发面工具：只读采样不改业务状态；Windows 下附着其他用户进程需管理员。</li>`) +
    `<h2 class='page'>剖析 <small>py-spy 火焰图（PR-8）</small></h2>
     <div class='panel'><b class='title'>环境</b> <span id='pf-status' class='muted'>检测中...</span></div>
     <div class='panel' style='margin-top:12px'>
       <b class='title'>采样</b>
       <div class='toolbar' style='margin-top:6px'>
         <b>目标</b><select id='pf-target'><option value='pid'>附着进程 pid</option><option value='cmd'>新起命令</option></select>
         <input id='pf-pid' size='10' placeholder='pid'>
         <input id='pf-cmd' size='34' placeholder='python scripts/x.py --flag（空格分词）'>
       </div>
       <div class='toolbar'>
         <b>时长 s</b><input id='pf-dur' value='30' style='width:70px'>
         <b>频率 Hz</b><input id='pf-rate' value='100' style='width:80px'>
         <b>格式</b><select id='pf-fmt'><option value='flamegraph'>flamegraph (.svg)</option><option value='speedscope'>speedscope (.json)</option></select>
         <button class='primary' id='pf-run'>开始采样</button>
         <span id='pf-msg' class='muted'></span>
       </div>
       <div id='pf-result' class='muted' style='margin-top:8px'></div>
     </div>`;
  const st = await T.api("/api/profile");
  T.$("pf-status").innerHTML = st.available
    ? `<span style='color:var(--ok)'>py-spy 可用（${esc(st.exe)}）</span>`
    : `<span style='color:var(--warn)'>${esc(st.hint || "py-spy 未安装")}</span>`;
  const syncTarget = () => {
    const mode = T.$("pf-target").value;
    T.$("pf-pid").style.display = mode === "pid" ? "" : "none";
    T.$("pf-cmd").style.display = mode === "cmd" ? "" : "none";
  };
  T.$("pf-target").onchange = syncTarget; syncTarget();
  T.$("pf-run").onclick = async () => {
    const mode = T.$("pf-target").value;
    const body = {
      duration_s: Number(T.$("pf-dur").value || 30),
      rate_hz: Number(T.$("pf-rate").value || 100),
      fmt: T.$("pf-fmt").value,
    };
    if (mode === "pid") body.pid = T.$("pf-pid").value.trim();
    else body.cmd = T.$("pf-cmd").value.trim().split(/\s+/).filter(Boolean);
    T.$("pf-msg").textContent = "采样中（页面可切走，采样在服务端）...";
    const r = await T.api("/api/profile", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    T.$("pf-msg").textContent = "";
    const el = T.$("pf-result");
    if (!r.ok) { el.innerHTML = `<span style='color:var(--err)'>✗ ${esc((r.errors || [r.error]).filter(Boolean).join("; "))}</span>`; return; }
    el.textContent = `✓ 产物：${r.output_path}（${r.fmt} · ${r.duration_s}s @ ${r.rate_hz}Hz）——runs/ 静态挂载开启时可直接在浏览器打开`;
  };
}

/* ═══ PR-9 调度队列页（ge8b Wave B 席B3）：战役队列 + G13 决策日志 ═══ */
async function pageQueue() {
  const v = T.$("view-queue");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>战役队列=runs/ 下已落盘的 campaign.plan.json（确定性拆解的阶段计划）；
          <b>决策日志</b>出自 G13 确定性调度前置步（派发顺序/预测时长来源/拒绝清单的审计事件）。</li>
      <li><b>remote 面</b>（可选）：填机器名后按战役显示 HFSS 阶段的远端附着配置增量
          （只读组装，零真连）；mTLS 是条件项，按远程资源说明口径如实登记。</li>
      <li>数据全部出自服务层既有函数，本页只渲染。</li>`) +
    `<h2 class='page'>调度队列 <small>战役计划 · G13 决策日志（PR-9）</small></h2>
     <div class='panel'>
       <div class='toolbar'><b>runs 根</b><input id='q-root' value='runs' style='width:200px'>
         <b>remote 机器</b><input id='q-machine' placeholder='（留空=不查 remote 面）' style='width:220px'>
         <button class='minor' id='q-reload'>刷新</button>
         <span id='q-info' class='muted'></span></div>
       <div id='q-table' style='margin-top:8px'></div>
     </div>
     <div id='q-detail' style='margin-top:12px'></div>`;
  async function load() {
    const q = new URLSearchParams({ root: T.$("q-root").value || "runs" });
    const machine = T.$("q-machine").value.trim();
    if (machine) q.set("machine", machine);
    const d = await T.api("/api/campaign_queue?" + q);
    const el = T.$("q-table");
    if (!d.ok) { el.innerHTML = `<span style='color:var(--err)'>✗ ${esc((d.errors || []).join("; "))}</span>`; return; }
    T.$("q-info").textContent = `${d.n_campaigns} 个战役计划${machine ? " · remote=" + machine : ""}`;
    if (!d.n_campaigns) { el.innerHTML = "<span class='muted'>runs/ 下暂无 campaign.plan.json（先立战役）</span>"; T.$("q-detail").innerHTML = ""; return; }
    el.innerHTML = `<table><thead><tr><th>战役</th><th>model</th><th>verdict</th>
      <th>阶段进度</th><th>调度</th><th>决策日志</th>${machine ? "<th>remote</th>" : ""}</tr></thead><tbody>` +
      d.campaigns.map((c) => {
        const done = (c.stages || []).filter((s) => s.status === "done").length;
        const dead = (c.stages || []).filter((s) => s.status === "failed" || s.status === "aborted").length;
        const dl = c.scheduling ? (c.scheduling.decision_log || []) : [];
        const name = String(c.path || "").replace(/\\/g, "/").split("/").slice(-2, -1)[0] || c.path;
        const remote = c.remote
          ? (c.remote.ok
            ? (c.remote.remote_machine
              ? `<span style='color:var(--ok)'>✓ ${esc(c.remote.remote_machine.remote_machine || c.remote.machine)}</span>`
              : "<span class='muted'>无配置（本地零变化）</span>")
            : `<span style='color:var(--warn)'>✗ ${esc((c.remote.errors || []).join("; "))}</span>`)
          : "";
        return `<tr><td title='${escAttr(c.path)}'>${esc(name)}</td><td>${esc(c.model || "?")}</td>
          <td>${T.badge(c.verdict || "—", c.verdict === "COMPLETE" ? "ok" : (c.verdict === "ABORTED" ? "err" : "muted"))}</td>
          <td>${done}/${c.n_stages}${dead ? ` <span style='color:var(--err)'>(死 ${dead})</span>` : ""}</td>
          <td>${c.scheduling && c.scheduling.ok ? `<span style='color:var(--ok)'>✓ ${esc(String(c.scheduling.n_jobs))} 作业</span>` : "<span class='muted'>—</span>"}</td>
          <td><a href='#' data-go='${escAttr(c.path)}' class='q-open'>${dl.length} 条</a></td>
          ${machine ? `<td>${remote}</td>` : ""}</tr>`;
      }).join("") + "</tbody></table>";
    T.$("q-detail").innerHTML = "";
    el.querySelectorAll(".q-open").forEach((a) => {
      a.onclick = (e) => {
        e.preventDefault();
        const c = d.campaigns.find((x) => x.path === a.dataset.go);
        if (c) renderDetail(c);
      };
    });
  }
  function renderDetail(c) {
    const dl = (c.scheduling && c.scheduling.decision_log) || [];
    const stages = c.stages || [];
    T.$("q-detail").innerHTML = `<div class='panel'>
      <b class='title'>${esc(c.model || c.path)} — 阶段与决策日志</b>
      <div style='margin:6px 0'>${stages.map((s) =>
        `${T.badge(s.stage + ":" + s.status, s.status === "done" ? "ok" : (s.status === "pending" ? "muted" : "err"))}${s.license_gated ? " <span class='muted'>(license)</span>" : ""}`).join(" ")}</div>
      ${dl.length
        ? `<table><thead><tr><th>#</th><th>决策</th></tr></thead><tbody>${dl.map((e, i) => {
            const line = typeof e === "string" ? e : JSON.stringify(e);
            return `<tr><td>${i + 1}</td><td>${esc(line)}</td></tr>`;
          }).join("")}</tbody></table>`
        : "<span class='muted'>该战役无决策日志（调度前置步未产出或旧计划）</span>"}
      ${c.remote ? `<div class='muted' style='margin-top:6px'>mTLS 状态：${esc(c.remote.mtls || "")}</div>` : ""}
    </div>`;
    T.$("q-detail").scrollIntoView({ block: "nearest" });
  }
  T.$("q-reload").onclick = load;
  T.$("q-machine").onchange = load;
  await load();
}
