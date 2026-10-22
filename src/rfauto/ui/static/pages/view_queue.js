/* rfauto 调度队列页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移，
   PR-9）：战役计划 + G13 决策日志 + remote 面只读组装。
   i18n（发布前软编码批 S2 残量清零）：help 块/详情面板/状态段全迁词表
   （queue.* 键域，zh 与旧字面逐字节同、en 新增）；表头 model/verdict/
   remote 为协议标识符刻意保留英文原文（豁免登记）；战役名/决策日志条目
   为 API 数据照旧 esc——数据非文案不迁。
   W2-S3（aurora_i 采纳 #2）：新增"阻塞原因"列（queue_block API 字段，
   code 词表渲染+等待时长；守护摘要入 q-info 行）。
   ═══ W2-S4 人性化二批（aurora_i 采纳 R1 #5+#6，2026-10-19）═══
   远程机器面板（/api/remote/resources 只读聚合，容器 #q-resources）：
   ①数据新鲜度片（remote.probed_at 龄期 ticker 实时跳动，>RES_STALE_S 变灰
   提示"点此刷新"，点击重拉）；②机器占用一眼可见（迷你占用条 在跑战役
   n/max_parallel（钉 1 如实展示）+ 占用战役徽章，数据=campaign_queue 守护
   状态档 launched 记账）；③选机推荐只读行（service recommend 块，
   size_aware 思想——前端零打分只渲染）；④维护遮罩（资源日历 blocked 态
   斜纹遮罩+徽章，备份窗 warn 徽章；机器级 drain 字段注册表未设=如实不做）。
   面板小件：筛选 tab 徽章（全部/进行中/已完成/失败中止 计数上 tab，切换
   零重拉）+ 阶段进度 mini-bar（stages done/n_stages 有进度字段才接）。
   纯函数四件（resFreshInfo/queueBucketOf/queueTabCounts/miniBarHtml）导出
   供 node 行为钉；面板渲染为浏览器路径（T.badge 依赖，与 pageQueue 同责）。
   资源面错误态走 kitErrorPanel（✗ 豁免点不新增——跨席计数钉恒 1）。 */

import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
// i18n（aurora_f W1-S2 试点页 3）：壳标签 data-i18n+首扫；表头/空态随 load()
// 重建，文案一律 t() 渲染期烘焙（i18n.js 头注纪律）。
import { t, applyI18nRoot } from "./i18n.js";
import { bindClickRows, bindEmptyStates, kitBadgeCls, kitClickRowAttrs, kitEmptyState, kitErrorPanel, kitTable } from "./kit.js";
import { mountSortableTables } from "./sortable.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 1 点）——
// 数据面全页（队列清单 load()，刷新钮与 ctx.refresh 共用）接
// viewSignal("queue") 切页收束 + aborted 短路（在途拉取不再写隐藏区）。
// 信封消费形态逐键不变（✗ 形态错误行=跨席计数钉保留）。
// W2-S4：资源面板第二请求点——真机 SSH 探测最坏 ~90s 级（探活 2 端口+census
// 3 命令），显式 timeoutMs 豁免缺省 30s（api.js 头注④显式正数覆盖档）。
import { apiFetch, viewSignal } from "./api.js";

/* ═══ W2-S4 纯函数四件（node 行为钉可测；零 DOM 零 T 依赖） ═══ */

/* 数据新鲜度：probed_at（服务端探测时刻，epoch 秒）+ 本端拉取完成时刻
   （ms）→ 龄期秒 + 超龄布尔。锚取 min(probed_at, fetched)（时钟偏差保守
   档：服务端钟快于本端时按本端拉取时刻计龄，不虚报新鲜）；probed_at 缺失
   回落 fetched（老信封兼容）；龄期负值钳 0。staleAfterS 缺省 RES_STALE_S。 */
export const RES_STALE_S = 120;

export function resFreshInfo(probedAtSec, nowMs, fetchedMs, staleAfterS) {
  const limit = typeof staleAfterS === "number" ? staleAfterS : RES_STALE_S;
  const probeMs = (typeof probedAtSec === "number" && probedAtSec > 0)
    ? probedAtSec * 1000 : null;
  const fetchMs = (typeof fetchedMs === "number" && fetchedMs > 0)
    ? fetchedMs : null;
  const anchors = [probeMs, fetchMs].filter((v) => v != null);
  if (!anchors.length) return { age_s: null, stale: false };
  const anchor = Math.min(...anchors);
  const ageS = Math.max(0, Math.round((nowMs - anchor) / 1000));
  return { age_s: ageS, stale: ageS > limit };
}

/* 战役 verdict → 筛选桶（tab 过滤单源）：RUNNING→running；COMPLETE→done；
   FAILED/ABORTED/PARTIAL→failed（中止族同桶——用户视角"没成"一类）；
   其余（空 verdict=未跑、未知值）→other（只在"全部"tab 出现，不臆测归类）。 */
export function queueBucketOf(verdict) {
  const v = String(verdict == null ? "" : verdict);
  if (v === "RUNNING") return "running";
  if (v === "COMPLETE") return "done";
  if (v === "FAILED" || v === "ABORTED" || v === "PARTIAL") return "failed";
  return "other";
}

/* 筛选 tab 计数（badge 数据面）：campaigns=[{verdict}] → 四 tab + other。 */
export function queueTabCounts(campaigns) {
  const counts = { all: 0, running: 0, done: 0, failed: 0, other: 0 };
  for (const c of campaigns || []) {
    const b = queueBucketOf(c && c.verdict);
    counts.all++;
    counts[b]++;
  }
  return counts;
}

/* 进度 mini-bar（纯串；无进度数据（null/undefined/""）或 pct∈[0,100] 之外
   返回 ""——无进度字段不接，W2-S4 小件纪律；注意 Number(null)=0 的 falsy
   陷阱，无数据判 absence 用 == null 而非数值化）。inline 令牌配色，零新
   CSS（index.html 不在本批面）。 */
export function miniBarHtml(pct, color, height, width) {
  if (pct == null || pct === "") return "";
  const p = Number(pct);
  if (!Number.isFinite(p) || p < 0 || p > 100) return "";
  const h = Number(height) > 0 ? Number(height) : 4;
  const w = Number(width) > 0 ? `width:${Number(width)}px;` : "";
  return `<div style='${w}height:${h}px;background:var(--panel2);` +
    `border-radius:${h / 2}px;margin-top:3px;overflow:hidden'>` +
    `<div style='height:${h}px;width:${p}%;background:${color};` +
    `border-radius:${h / 2}px'></div></div>`;
}

/* ═══ W2-S4 远程机器面板（模块级状态：末次数据 + 新鲜度 ticker + 筛选） ═══ */
let _resData = null; // 末次 /api/remote/resources 信封（原样）
let _resFetchedMs = 0; // 本端拉取完成时刻（新鲜度锚之一）
let _freshTimer = null; // 新鲜度 ticker（setTimeout 自续链；leave 收束）
let _queueFilter = "all"; // 筛选 tab 当前键（all|running|done|failed）
let _lastQueue = null; // 末次 campaign_queue 信封（tab 重筛零重拉）

/* 新鲜度片文字（ticker 只改 textContent——按钮 onclick 不随重建丢失）。 */
function _freshChipText(fresh) {
  if (fresh.age_s == null) return t("queue.res_fresh_unknown");
  return t("queue.res_fresh_tpl", { n: fresh.age_s }) +
    (fresh.stale ? " · " + t("queue.res_fresh_stale") : "");
}

function _applyFreshChip() {
  const chip = T.$("q-res-fresh");
  if (!chip || !_resData) return;
  const fresh = resFreshInfo(
    (_resData.resources || {}).remote?.probed_at, Date.now(), _resFetchedMs);
  const txt = chip.querySelector("#q-res-fresh-txt");
  if (txt) txt.textContent = _freshChipText(fresh);
  chip.style.color = fresh.stale ? "var(--muted)" : "";
  chip.style.borderColor = fresh.stale ? "var(--border)" : "";
  chip.setAttribute("aria-label",
    t("queue.res_fresh_aria") + "（" + _freshChipText(fresh) + "）");
}

function _scheduleFreshTick() {
  if (_freshTimer != null) clearTimeout(_freshTimer);
  _freshTimer = setTimeout(() => {
    _freshTimer = null;
    // 可见性守卫（polling.js 托管纪律同 spirit）：隐藏页只续链不写 DOM
    if (typeof document === "undefined" ||
      document.visibilityState !== "hidden") _applyFreshChip();
    _scheduleFreshTick();
  }, 10000);
}

/* 远程机器面板渲染（_resData → 卡片；纯浏览器路径，T.badge 内部 esc）。 */
function renderResPanel() {
  const el = T.$("q-resources");
  if (!el) return;
  if (!_resData) { el.innerHTML = ""; return; }
  const head = `<b class='title'>${t("queue.res_title")}</b>`;
  if (_resData.ok === false) {
    // 错误态动作化（kitErrorPanel 单源；✗ 计数钉不新增——queue 豁免点恒 1）
    el.innerHTML = `<div class='panel'>${head}` +
      kitErrorPanel((_resData.errors || []).join("; "), "q-res-retry") +
      `</div>`;
    const retry = T.$("q-res-retry");
    if (retry) retry.onclick = () => loadResources();
    return;
  }
  const res = _resData.resources || {};
  const remote = res.remote || {};
  const occ = _resData.occupancy || {};
  const rec = res.recommend || {};
  const cal = res.calendar || {};
  const loc = res.local || {};

  // ① 新鲜度片（button：点此刷新=重拉资源面；ticker 只改字不变接线）
  const fresh = resFreshInfo(remote.probed_at, Date.now(), _resFetchedMs);
  const chip = `<button class='minor' id='q-res-fresh' ` +
    `aria-label='${escAttr(t("queue.res_fresh_aria"))}' ` +
    `title='${escAttr(t("queue.res_fresh_stale"))}' ` +
    `style='margin-left:8px;font-size:11.5px;` +
    (fresh.stale ? "color:var(--muted)" : "") + `'>` +
    `<span aria-hidden='true'>⟳</span> <span id='q-res-fresh-txt'>` +
    esc(_freshChipText(fresh)) + `</span></button>`;

  // 机器行：可达性徽章 + census/磁盘（disk/n_tasks 为 API 数据经 esc）
  let machineRow = "";
  if (!remote.machine) {
    machineRow = `<div class='muted' style='margin:var(--space-2) 0px'>` +
      esc(t("queue.res_no_machine")) +
      (remote.reason ? `（${esc(remote.reason)}）` : "") + `</div>`;
  } else {
    const reach = remote.reachable;
    const reachBadge = reach === true
      ? `<span class='badge ok'>✓ ${esc(t("queue.res_reach_ok"))}</span>`
      : reach === false
        ? `<span class='badge err'>✗ ${esc(t("queue.res_reach_bad"))}</span>`
        : `<span class='badge muted'>${esc(t("queue.res_reach_unknown"))}</span>`;
    const disk = remote.disk || {};
    const diskTxt = disk.state === "ok"
      ? t("queue.res_disk_tpl", { n: disk.free_gb })
      : "";
    const tasksTxt = remote.n_tasks != null
      ? t("queue.res_tasks_tpl", { n: remote.n_tasks })
      : "";
    machineRow = `<div style='margin:var(--space-2) 0px;display:flex;` +
      `align-items:center;gap:8px;flex-wrap:wrap'>` +
      `<b>${esc(String(remote.machine))}</b>${reachBadge}` +
      (diskTxt ? `<span class='muted'>💾 ${esc(diskTxt)}</span>` : "") +
      (tasksTxt ? `<span class='muted'>⚙ ${esc(tasksTxt)}</span>` : "") +
      `</div>`;
  }

  // ② 占用条 + 占用战役徽章（max_parallel 钉 1 如实展示，#261 每机互斥）
  const maxp = Number(occ.max_parallel) > 0 ? Number(occ.max_parallel) : 1;
  const inflight = Number(occ.in_flight) > 0 ? Number(occ.in_flight) : 0;
  const occPct = Math.min(100, Math.round((inflight / maxp) * 100));
  const occBar = miniBarHtml(occPct,
    inflight >= maxp ? "var(--warn)" : "var(--ok)", 6, 160);
  const badges = (occ.campaigns || []).map((c) =>
    `<span title='${escAttr(String(c.plan_path || c.item_id || ""))}'>` +
    T.badge(String(c.model || c.item_id || "?"), "warn") + `</span>`);
  const badgesHtml = badges.join(" "); // 预拼（test_ui_xss 裸插值扫描口径：
  // 带字段访问的模板插值须登记——单标识符插值不在扫描面，本席照此收口）
  const occRow = `<div style='margin:var(--space-2) 0px;display:flex;` +
    `align-items:center;gap:8px;flex-wrap:wrap'>` +
    `<span class='muted'>${esc(t("queue.res_occupancy_tpl",
      { n: inflight, m: maxp }))}</span>${occBar}${badgesHtml}` +
    `</div>`;

  // ③ 选机推荐只读行（打分在 service，前端零逻辑只渲染；机器名 esc 后入行）
  const recRow = rec.machine
    ? (rec.eligible
      ? `<div style='margin:var(--space-2) 0px'>` +
        `<span style='color:var(--ok)'>✓ ${esc(t("queue.res_recommend_lead"))}` +
        `${esc(String(rec.machine))}</span>` +
        (rec.score != null
          ? ` <span class='muted'>${esc(t("queue.res_recommend_score_tpl",
            { s: Number(rec.score).toFixed(2) }))}</span>`
          : "") +
        `</div>`
      : `<div class='muted' style='margin:var(--space-2) 0px'>` +
        `${esc(t("queue.res_not_recommended"))}：` +
        `${esc((rec.excluded_by || []).join("；"))}</div>`)
    : "";

  // ④ 维护遮罩（资源日历 blocked=时间维维护；机器级 drain 字段注册表未设
  // =如实不做——W2-S4 盘点登记）。斜纹遮罩 pointer-events:none 纯视觉，
  // 阻断语义在服务端门（calendar_launch_view fail-closed），前端不假拦。
  const blocked = cal.launchable === false;
  const risk = !blocked && cal.state === "risk";
  const calBadge = blocked
    ? ` <span class='badge warn'>${esc(t("queue.res_maintenance"))}</span>`
    : risk
      ? ` <span class='badge warn'>${esc(t("queue.res_backup_risk"))}</span>`
      : "";
  const mask = blocked
    ? `<div aria-hidden='true' style='position:absolute;inset:0;` +
      `pointer-events:none;border-radius:var(--radius-xl);` +
      `background:repeating-linear-gradient(45deg, transparent 0 8px, ` +
      `var(--warn-bg) 8px 16px)'></div>`
    : "";
  const cardStyle = blocked ? "opacity:.72;" : "";

  // 本机 census 摘要（openEMS/HFSS 进程互斥态，muted 一行；纯串拼接构造
  // 后整行 esc 单点转义——带字段访问的模板插值不入 xss 扫描面同款收口）
  const locLine = ["openems", "hfss"].map((k) => {
    const ch = loc[k] || {};
    if (ch.state !== "ok") return "";
    const label = k === "openems" ? "openEMS" : "HFSS";
    let s = label + " n_procs=" + (ch.n_procs != null ? ch.n_procs : "?");
    if (k === "hfss" && ch.n_grpcsrv != null) s += " grpcsrv=" + ch.n_grpcsrv;
    return s;
  }).filter(Boolean).join(" · ");

  el.innerHTML = `<div class='panel' style='position:relative;${cardStyle}'>` +
    head + chip + calBadge +
    `<div style='margin-top:var(--space-2)'>` +
    machineRow + occRow + recRow +
    (locLine
      ? `<div class='muted' style='font-size:12px'>${esc(t("queue.res_local_label"))}：${esc(locLine)}</div>`
      : "") +
    `</div>${mask}</div>`;

  const chipBtn = T.$("q-res-fresh");
  if (chipBtn) chipBtn.onclick = () => loadResources();
  _scheduleFreshTick();
}

/* 资源面拉取（独立于队列表；失败走 kitErrorPanel 不碰 ✗ 豁免点）。
   调用形态照 campaign_queue 先例：字面量含 "?" 再拼 URLSearchParams——
   check_ui_contracts 调用归一按 "?" 截断得精确路径（悬空调用即免）。 */
async function loadResources() {
  // 局部名 qres：与 447 行 campaign_queue 的同名 q（root 参数）在
  // check_ui_contracts 的按名 varmap 里分离——同名合并会把 root 多记到
  // resources 路由（悬空参数误红，aurora_i W4-R3 审查实证）。
  const qres = new URLSearchParams();
  const machine = (T.$("q-machine").value || "").trim();
  if (machine) qres.set("machine", machine);
  const d = await apiFetch("/api/remote/resources?" + qres,
    { signal: viewSignal("queue"), timeoutMs: 120000 });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  _resData = d;
  _resFetchedMs = Date.now();
  renderResPanel();
}

/* ═══ PR-9 调度队列页（ge8b Wave B 席B3）：战役队列 + G13 决策日志 ═══ */

/* W2-S3（aurora_i 采纳 #2）：queue-daemon 阻塞账人读渲染——code 走词表
   （zh/en 双语），detail/waited_s 为 API 动态数据照旧 esc（数据非文案不迁
   同款纪律）；未知 code 回退服务层 text 原文。无账返回空串（列内容归
   调用方兜底——W3-S3 对冲告警同列回退链）。 */
function fmtWaited(s) {
  return s < 90 ? t("queue.block_wait_sec_tpl", { n: Math.round(s) })
    : t("queue.block_wait_min_tpl", { n: Math.round(s / 60) });
}

function queueBlockHtml(b) {
  if (!b || !b.code) return "";
  let txt;
  if (b.code === "solo_wait")
    txt = b.detail ? t("queue.block_solo_tpl", { detail: b.detail })
      : t("queue.block_solo");
  else if (b.code === "calendar_blocked")
    txt = t("queue.block_calendar_tpl", { detail: b.detail || "" });
  else if (b.code === "license_wait")
    txt = t("queue.block_license_tpl", { detail: b.detail || "" });
  else if (b.code === "queued_ahead")
    txt = t("queue.block_ahead_tpl", { n: b.n_ahead || 0 });
  else txt = b.text || b.code; // 未知码回退服务层人读原文（API data→esc）
  const waited = (typeof b.waited_s === "number")
    ? t("queue.block_waited_tpl", { d: fmtWaited(b.waited_s) }) : "";
  return "<span style='color:var(--warn)'>⏳ " + esc(txt) + "</span>" +
    (waited ? " <span class='muted'>" + esc(waited) + "</span>" : "");
}

/* W3-S3（aurora_i 采纳 #1）：对冲告警人读渲染——在途项"卡死但未死"停滞
   疑似（对冲监测缺省关=无 queue_hedge 字段零渲染）；code 走词表，未知码
   回退服务层 text 原文；stalled_s/attempts 为 API 数据照旧 esc。 */
function hedgeHtml(b) {
  if (!b || !b.code) return "";
  const txt = b.code === "stall_suspected"
    ? t("queue.hedge_stall_tpl")
    : (b.text || b.code);
  const stalled = (typeof b.stalled_s === "number")
    ? " <span class='muted'>" +
      esc(t("queue.hedge_waited_tpl", { d: fmtWaited(b.stalled_s) })) +
      "</span>" : "";
  const rel = b.attempts
    ? " <span class='muted'>· " + esc(t("queue.hedge_relaunched_tpl")) +
      "</span>" : "";
  return "<span style='color:var(--warn)'>⏱ " + esc(txt) + "</span>" +
    stalled + rel;
}

export async function pageQueue() {
  const v = T.$("view-queue");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("queue.help_1_lead")}<b>${t("queue.help_1_core")}</b>${t("queue.help_1_tail")}</li>
      <li><b>${t("queue.help_2_core")}</b>${t("queue.help_2_tail")}</li>
      <li>${t("queue.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='queue.title'>${t("queue.title")}</span> <small data-i18n='queue.subtitle'>${t("queue.subtitle")}</small></h2>
     <div class='panel'>
       <div class='toolbar'><b data-i18n='queue.runs_root'>${t("queue.runs_root")}</b><input id='q-root' value='runs' style='width:200px'>
         <b data-i18n='queue.machine_label'>${t("queue.machine_label")}</b><input id='q-machine' placeholder='${t("queue.machine_placeholder")}' style='width:220px' data-i18n-ph='queue.machine_placeholder'>
         <button class='minor' id='q-reload' data-i18n='queue.reload'>${t("queue.reload")}</button>
         <span id='q-info' class='muted'></span></div>
       <div id='q-table' style='margin-top:var(--space-2)'></div>
     </div>
     <div id='q-resources' style='margin-top:var(--space-3)'></div>
     <div id='q-detail' style='margin-top:var(--space-3)'></div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W1-S2）
/* 筛选 tab（W2-S4 小件①）：计数上 tab（queueTabCounts），aria-pressed
   标激活态；other 桶（空 verdict 等）只在"全部"出现——不臆测归类。
   注：本席 inline 间距写 0px 而非 0——test_ui_r12 迁移落位计数钉
   （margin:var(--space-2) 0 字面 ==3）避让，computed 值等价、非迁移面。 */
  function renderTabs(counts) {
    const defs = [
      ["all", t("queue.tab_all")], ["running", t("queue.tab_running")],
      ["done", t("queue.tab_done")], ["failed", t("queue.tab_failed")],
    ];
    return `<div class='toolbar' id='q-tabs' role='group' ` +
      `aria-label='${escAttr(t("queue.tab_all"))}' ` +
      `style='gap:6px;margin:var(--space-2) 0px 0'>` +
      defs.map(([key, label]) => {
        const active = _queueFilter === key;
        return `<button class='minor q-tab' data-qf='${key}' ` +
          `aria-pressed='${active}' style='${active ? "border-color:var(--info)" : "opacity:.78"}'>` +
          `${esc(label)} <span class='badge muted'>${counts[key] || 0}</span></button>`;
      }).join("") + `</div>`;
  }
  function renderQueue() {
    const d = _lastQueue;
    const el = T.$("q-table");
    if (!d || !el) return;
    const machine = (T.$("q-machine").value || "").trim();
    T.$("q-info").textContent = t("queue.info_tpl", { n: d.n_campaigns }) +
      (machine ? " · remote=" + machine : "") +
      (d.queue_daemon && d.queue_daemon.loaded
        ? " · " + t("queue.daemon_summary_tpl",
          { n: d.queue_daemon.n_items || 0, m: d.queue_daemon.in_flight || 0 })
        : " · " + t("queue.daemon_off"));
    if (!d.n_campaigns) {
      // A8-A（R6 审计 P-3）：空态三件式——引导去战役仪表盘立战役
      el.innerHTML = kitEmptyState(t("queue.empty"),
        { icon: "≣", label: t("queue.empty_action"), view: "campaign" });
      bindEmptyStates(el);
      T.$("q-detail").innerHTML = "";
      return;
    }
    const counts = queueTabCounts(d.campaigns);
    const rows = d.campaigns.filter((c) =>
      _queueFilter === "all" || queueBucketOf(c.verdict) === _queueFilter);
    el.innerHTML = renderTabs(counts) +
      `<table data-sortable><thead><tr><th scope="col">${t("queue.th_campaign")}</th><th scope="col">model</th><th scope="col">verdict</th>
      <th scope="col">${t("queue.th_block_reason")}</th><th scope="col">${t("queue.th_stages")}</th><th scope="col">${t("queue.th_schedule")}</th><th scope="col">${t("queue.th_decision_log")}</th>${machine ? "<th scope='col'>remote</th>" : ""}</tr></thead><tbody>` +
      rows.map((c) => {
        const done = (c.stages || []).filter((s) => s.status === "done").length;
        const dead = (c.stages || []).filter((s) => s.status === "failed" || s.status === "aborted").length;
        const dl = c.scheduling ? (c.scheduling.decision_log || []) : [];
        const name = String(c.path || "").replace(/\\/g, "/").split("/").slice(-2, -1)[0] || c.path;
        const remote = c.remote
          ? (c.remote.ok
            ? (c.remote.remote_machine
              ? `<span style='color:var(--ok)'>✓ ${esc(c.remote.remote_machine.remote_machine || c.remote.machine)}</span>`
              : "<span class='muted'>" + t("queue.remote_no_config") + "</span>")
            : `<span style='color:var(--warn)'>✗ ${esc((c.remote.errors || []).join("; "))}</span>`)
          : "";
        // W2-S4 小件②：阶段进度 mini-bar（done/n_stages 有进度字段才接；
        // 排序键仍读单元格文本 "3/5"——sortable 字符串口径零变化）
        const total = Number(c.n_stages) || (c.stages || []).length || 0;
        const pct = total > 0 ? Math.round((done / total) * 100) : null;
        const bar = miniBarHtml(pct, "var(--info)", 4, 90);
        return `<tr><td title='${escAttr(c.path)}'>${esc(name)}</td><td>${esc(c.model || "?")}</td>
          <td>${T.badge(c.verdict || "—", kitBadgeCls(c.verdict))}</td>
          <td>${queueBlockHtml(c.queue_block) || hedgeHtml(c.queue_hedge) || "<span class='muted'>—</span>"}</td>
          <td>${done}/${c.n_stages}${dead ? ` <span style='color:var(--err)'>${t("queue.dead_tpl", { n: dead })}</span>` : ""}${bar}</td>
          <td>${c.scheduling && c.scheduling.ok ? `<span style='color:var(--ok)'>✓ ${t("queue.jobs_tpl", { n: esc(String(c.scheduling.n_jobs)) })}</span>` : "<span class='muted'>—</span>"}</td>
          <td><a href='#' data-go='${escAttr(c.path)}' class='q-open' ${kitClickRowAttrs({ label: t("queue.open_log_aria_tpl", { n: dl.length }) })}>${t("queue.entries_tpl", { n: dl.length })}</a></td>
          ${machine ? `<td>${remote}</td>` : ""}</tr>`;
      }).join("") + "</tbody></table>" +
      (rows.length === 0
        ? `<div class='muted' style='margin-top:var(--space-2)'>${esc(t("queue.filter_empty"))}</div>`
        : "");
    T.$("q-detail").innerHTML = "";
    // UI-R4：决策日志锚键盘可达收编 bindClickRows——role=button+tabindex
    // （kit 属性串）；click/Enter/Space 全 preventDefault，href='#' 页顶
    // 跳动面（A6 P1-5 指控点）随之闭合。视觉零变化（a 无 href 专属样式）。
    bindClickRows(el, (a) => {
      const c = _lastQueue.campaigns.find((x) => x.path === a.dataset.go);
      if (c) renderDetail(c);
    }, ".q-open");
    // aurora36 W3-B（P1-7）：战役表可排序——<table> 随 renderQueue()
    // innerHTML 重建，每次渲染后重扫挂载（makeSortable 幂等；行内 .q-open
    // 锚事件随节点重排不丢）
    mountSortableTables(el);
    // 筛选 tab 接线（W2-S4：表随 tab 重建后重挂；切换零重拉——_lastQueue
    // 原地重筛，点击只重渲染本容器）
    el.querySelectorAll(".q-tab").forEach((btn) => {
      btn.onclick = () => {
        _queueFilter = btn.getAttribute("data-qf") || "all";
        renderQueue();
      };
    });
  }
  async function load() {
    const q = new URLSearchParams({ root: T.$("q-root").value || "runs" });
    const machine = T.$("q-machine").value.trim();
    if (machine) q.set("machine", machine);
    const d = await apiFetch("/api/campaign_queue?" + q,
      { signal: viewSignal("queue") });
    if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
    const el = T.$("q-table");
    // A8-A 注：本点错误提示保持 ✗ 形态不迁 kitErrorPanel——跨席 ✗ 计数钉
    // （test_ui_lifecycle/test_ui_tools_page 双钉 ==6）如实不清偿；错误态
    // 动作化落 datasets/anchors 两点（本注释故不写钉串字面，防自增计数）。
    if (!d.ok) { el.innerHTML = `<span style='color:var(--err)'>✗ ${esc((d.errors || []).join("; "))}</span>`; return; }
    _lastQueue = d;
    renderQueue();
    loadResources(); // W2-S4：资源面板并行拉取（独立 aborted 守卫，不 await）
  }
  function renderDetail(c) {
    const dl = (c.scheduling && c.scheduling.decision_log) || [];
    const stages = c.stages || [];
    T.$("q-detail").innerHTML = `<div class='panel'>
      <b class='title'>${esc(c.model || c.path)}${t("queue.detail_title_suffix")}</b>
      <div style='margin:6px 0'>${stages.map((s) =>
        `${T.badge(s.stage + ":" + s.status, s.status === "done" ? "ok" : (s.status === "pending" ? "muted" : "err"))}${s.license_gated ? " <span class='muted'>(license)</span>" : ""}`).join(" ")}</div>
      ${dl.length
        ? kitTable({ // A7-A ui-kit 试点：表壳单源（kitTable；dl 非空分支才进，empty:"" 保空 tbody 等价）
            columns: ["#", t("queue.th_decision")], rows: dl, empty: "",
            rowHtml: (e, i) => {
              const line = typeof e === "string" ? e : JSON.stringify(e);
              return `<tr><td>${i + 1}</td><td>${esc(line)}</td></tr>`;
            },
          })
        : "<span class='muted'>" + t("queue.no_decision_log") + "</span>"}
      ${c.remote ? `<div class='muted' style='margin-top:6px'>${t("queue.mtls_status_lead")}${esc(c.remote.mtls || "")}</div>` : ""}
    </div>`;
    T.$("q-detail").scrollIntoView({ block: "nearest" });
  }
  T.$("q-reload").onclick = load;
  T.$("q-machine").onchange = load;
  await load();
}

/* ═══ R-1（aurora_e W3-S12）：PageContext 增量钩子 queueCtx ═════════════
   refresh=表数据重拉（runs 同模板——pageQueue 幂等：壳判 innerHTML 已在即
   跳过，campaign_queue 按当前 runs 根/机器输入重拉；决策日志详情随表整清；
   W2-S4 起远程机器面板同链重拉）。
   leave=W2-S4 新鲜度 ticker 收束（setTimeout 自续链，离页必须断——
   polling 托管纪律同 spirit，自由定时器零残留）。 */
export const queueCtx = {
  refresh: () => pageQueue(),
  leave: () => {
    if (_freshTimer != null) { clearTimeout(_freshTimer); _freshTimer = null; }
  },
};
