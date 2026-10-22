/* rfauto 模板画廊页（aurora_d UI-R2 自 pages.js 拆出，PR-5）。
   R2 人性化改造席（用户实测批次 2026-10-19）：72 卡全量详情抽屉——
   ①一句话人话说明（gallery.desc_* 词表，缺席回退 topology 首句清洗）
   ②参数白话表（param_semantics 前端解析 + 附加键白话兜底 + 数值来源列）
   ③有预览通道才显示闭式预览，没有的显示诚实一行（不再满屏"未配通道"
   徽标，卡角仅留小标记）。卡面瘦身：参数串折叠进抽屉。
   aurora_i W2-S1（可信度锚对照卡，R3 设计 M1）：抽屉加"可信度"节——
   HFSS 仲裁锚按 template_family（含 * 通配）渲染，/api/anchors 摘要 +
   /api/anchors/{id} 详情惰性补拉，零新端点（实现注记见锚节头注）。
   aurora_i W3-S2（对照曲线节，R3 设计 M3 前端半）：抽屉加"对照曲线"节——
   /api/credibility/curves?template=<name>（W3-S1 服务席端点）叠加图：
   双引擎对=HFSS/openEMS 两线+图例+偏差注记；单引擎=单线+note；无数据
   =整节隐藏（display:none 缺省，数据定局才揭示）。数据面在
   cred_curves.js 纯数据模块（normalize/偏差/缓存），本文件只做渲染。
   映射/量程解释仍在 service/gallery_service（前端只渲染）；预览数值全部
   出自 /api/calculators/run 闭式纯函数（零 EM 求解）。 */

import { T } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
// 三态收敛（aurora_f W2-S5，R1 #8 批1）：错误=kitErrorPanel、空态=kitEmptyState
import { kitEmptyState, kitErrorPanel } from "./kit.js";
// i18n（aurora_f W1-S2 试点页 2）：壳标签 data-i18n+首扫；卡面/抽屉随
// 数据重建，文案一律 t() 渲染期烘焙（i18n.js 头注纪律）。
import { t, applyI18nRoot } from "./i18n.js";
// P8-9（aurora_f W4-S13，R1 §面4）：T.api→apiFetch 统一请求层——数据面
// （模板卡清单）接 viewSignal("gallery") 切页收束 + aborted 短路；动作面
// （闭式预览计算 POST）保持无 signal（用户动作不被切页取消）。
import { apiFetch, viewSignal } from "./api.js";
// W3-S2 对照曲线数据面（cred_curves.js 纯数据模块：normalize/偏差注记/
// series 组装/取数缓存——渲染在本文件，i18n 文案在此烘焙）。
import { credFetch, credSeriesLabeled, credMaxDev, credEngineTag } from "./cred_curves.js";
// 引擎色对取档（theme.js 单源——cred_curves 色对经 themePick(light)）
import { bodyIsLight } from "../theme.js";

/* 模板卡缓存（W6-S2 S 状态收编：属主=本模块，契约表见 context.js；
   进页重拉语义不变；test_ui_modules_behavior 钉模块级 let 在位）。 */
let _galCards = null;

/* 当前打开的详情抽屉（单例：再点他卡先关旧的，Esc/遮罩/关闭钮三通道；
   Esc 监听随抽屉同生命周期——closeDrawer 单点拆卸，零泄漏）。 */
let _drawerEl = null;
let _drawerKeyHandler = null;

/* ═══ 72 模板一句话人话说明（R2 人性化席）════════════════════════════
   键尾=模板名，词表键 gallery.desc_*（zh+en 双语，i18n.js 同批）。
   字面映射表（view_tools CALC_I18N 先例）：键集互证按引号字面收录——
   动态拼键（gallery.desc_ 前缀拼模板名）会逃逸 _PAGE_KEY_LIT 扫描造成
   死键误红，故逐一落本表；新模板注册时同批补词表键+本表；缺席回退
   topology 首句清洗（cardDesc），再缺席 gallery.desc_missing 诚实行。 */
const DESC_KEYS = {
  atten_pi: "gallery.desc_atten_pi",
  atten_t: "gallery.desc_atten_t",
  bend: "gallery.desc_bend",
  branchline: "gallery.desc_branchline",
  branchline_2sect: "gallery.desc_branchline_2sect",
  cline_coupler: "gallery.desc_cline_coupler",
  coax_waveguide_transition: "gallery.desc_coax_waveguide_transition",
  coil_nfc: "gallery.desc_coil_nfc",
  combline: "gallery.desc_combline",
  coupled_bpf: "gallery.desc_coupled_bpf",
  coupled_line: "gallery.desc_coupled_line",
  cps: "gallery.desc_cps",
  cpw: "gallery.desc_cpw",
  diplexer: "gallery.desc_diplexer",
  dipole: "gallery.desc_dipole",
  embedded_ms: "gallery.desc_embedded_ms",
  fgcpw: "gallery.desc_fgcpw",
  gysel: "gallery.desc_gysel",
  hairpin: "gallery.desc_hairpin",
  hairpin_alt: "gallery.desc_hairpin_alt",
  helix: "gallery.desc_helix",
  hmsiw: "gallery.desc_hmsiw",
  ifa: "gallery.desc_ifa",
  interdigital: "gallery.desc_interdigital",
  inverted_ms: "gallery.desc_inverted_ms",
  isl_shielded: "gallery.desc_isl_shielded",
  lange: "gallery.desc_lange",
  loop: "gallery.desc_loop",
  marchand_balun: "gallery.desc_marchand_balun",
  mline: "gallery.desc_mline",
  mmwave_series_array: "gallery.desc_mmwave_series_array",
  monopole: "gallery.desc_monopole",
  ms_array_NxN: "gallery.desc_ms_array_nxn",
  ms_cross: "gallery.desc_ms_cross",
  ms_jcross: "gallery.desc_ms_jcross",
  ms_mushroom: "gallery.desc_ms_mushroom",
  ms_patch: "gallery.desc_ms_patch",
  ms_ring_patch: "gallery.desc_ms_ring_patch",
  msl_cpw: "gallery.desc_msl_cpw",
  msl_siw_taper: "gallery.desc_msl_siw_taper",
  msl_slot_transition: "gallery.desc_msl_slot_transition",
  nway_wilkinson: "gallery.desc_nway_wilkinson",
  patch: "gallery.desc_patch",
  patch_array_1x4: "gallery.desc_patch_array_1x4",
  patch_array_2x2: "gallery.desc_patch_array_2x2",
  patch_array_series: "gallery.desc_patch_array_series",
  patch_eep_1x4: "gallery.desc_patch_eep_1x4",
  patch_eep_2x2: "gallery.desc_patch_eep_2x2",
  pifa: "gallery.desc_pifa",
  pyramid_horn: "gallery.desc_pyramid_horn",
  qwt_multisection: "gallery.desc_qwt_multisection",
  ratrace: "gallery.desc_ratrace",
  ridged_wg: "gallery.desc_ridged_wg",
  ring_resonator: "gallery.desc_ring_resonator",
  schiffman: "gallery.desc_schiffman",
  sicl: "gallery.desc_sicl",
  sir_bpf: "gallery.desc_sir_bpf",
  siw: "gallery.desc_siw",
  slot: "gallery.desc_slot",
  slotline: "gallery.desc_slotline",
  slotline_lumped: "gallery.desc_slotline_lumped",
  sma_launcher: "gallery.desc_sma_launcher",
  stepped_impedance: "gallery.desc_stepped_impedance",
  stripline: "gallery.desc_stripline",
  suspended_stripline: "gallery.desc_suspended_stripline",
  tjunc: "gallery.desc_tjunc",
  varactor_bpf: "gallery.desc_varactor_bpf",
  via: "gallery.desc_via",
  vivaldi_tsa: "gallery.desc_vivaldi_tsa",
  wilkinson: "gallery.desc_wilkinson",
  wstep: "gallery.desc_wstep",
  xcheb_bpf4: "gallery.desc_xcheb_bpf4",
};

/* ═══ 附加名义参数白话兜底（R2）════════════════════════════════════
   nominal_params 里 base 材料常量/单模板附加键不在 meta.params 清单、
   param_semantics 也不覆盖（er×25/tan_d×22/h_mm×11 等）——键名→词表键
   gallery.gloss_*。语义段有解释的键优先走语义段（本表只兜底）。 */
const GLOSS_KEYS = {
  er: "gallery.gloss_er",
  tan_d: "gallery.gloss_tan_d",
  h_mm: "gallery.gloss_h_mm",
  h_sub_mm: "gallery.gloss_h_sub_mm",
  f0_ghz: "gallery.gloss_f0_ghz",
  load_r_ohm: "gallery.gloss_load_r_ohm",
  r_ring_mm: "gallery.gloss_r_ring_mm",
};

/* 基板材料常量键集（数值来源列=基板常量，区别于可改设计值）。 */
const SUBSTRATE_KEYS = new Set(["er", "tan_d", "h_mm", "h_sub_mm"]);

/* ═══ param_semantics 白话段解析（R2，纯展示层）════════════════════
   注册表语义文本形态："a_mm=…，b_mm/c_mm=…，gaps_mm[j]=…"——按已知参数
   名切段。支持三形态：单名 name=；斜杠组 w_a/w_b=（多参数共用一条说明，
   末成员后缀继承给前缀成员，xcheb g12/g23/g34_mm= 实证）；数组下标
   gaps_mm[j]=（下标剥离）。未命中参数诚实回退 sem_missing（不猜）。
   全 72 模板 324 参数实测全覆盖（2026-10-19 注册表面）。 */
function parseSemantics(sem, params) {
  const out = {};
  if (!sem) return out;
  const pset = new Set(params || []);
  const re = /([a-z][a-z0-9_]*(?:\[[a-z0-9_]+\])?(?:\/[a-z][a-z0-9_]*(?:\[[a-z0-9_]+\])?)*)\s*[=＝]/g;
  const spans = [];
  let m;
  while ((m = re.exec(sem))) {
    const members = m[1].replace(/\[[a-z0-9_]+\]/g, "").split("/");
    // 斜杠组后缀继承：末成员 _mm 类后端授予同组裸前缀成员（g12→g12_mm）
    const suf = members.length > 1
      ? ((members[members.length - 1].match(/(_[a-z]+)$/) || [])[1] || "")
      : "";
    const names = [];
    for (const x of members) {
      if (pset.has(x)) { names.push(x); continue; }
      if (suf && pset.has(x + suf) && names.indexOf(x + suf) < 0)
        names.push(x + suf);
    }
    if (names.length)
      spans.push({ at: m.index, eqEnd: m.index + m[0].length, names });
  }
  for (let i = 0; i < spans.length; i++) {
    const end = i + 1 < spans.length ? spans[i + 1].at : sem.length;
    const text = sem.slice(spans[i].eqEnd, end).trim()
      .replace(/[，,；;、]+$/, "").trim();
    if (!text) continue;
    for (const p of spans[i].names) if (!out[p]) out[p] = text;
  }
  return out;
}

/* 参数表行序：设计参数（meta.params 序）在前，附加名义键随后。 */
function orderedParams(c) {
  const nom = c.nominal_params || {};
  const pl = c.params || [];
  const head = pl.filter((k) => k in nom);
  const tail = Object.keys(nom).filter((k) => pl.indexOf(k) < 0);
  return head.concat(tail);
}

/* 名义值渲染（数组逐项逗号拼；嵌套对象 JSON 折叠；空值诚实短横）。 */
function fmtVal(v) {
  if (v === null || v === undefined) return "-";
  if (Array.isArray(v))
    return v.map((x) => (typeof x === "object" && x !== null
      ? JSON.stringify(x) : String(x))).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/* 数值来源列（人话三分类：可调设计值 / 基板常量 / 设计中心频率，
   附加键兜底 origin_other；预览通道命中键标可拖动试算）。 */
function paramOrigin(c, k) {
  if (k === "f0_ghz") return t("gallery.origin_f0");
  if (SUBSTRATE_KEYS.has(k)) return t("gallery.origin_substrate");
  const srcs = (c.preview && c.preview.sources) || {};
  if (Object.keys(srcs).length && Object.keys(srcs)
    .some((p) => srcs[p] === k)) return t("gallery.origin_tunable");
  if ((c.params || []).indexOf(k) >= 0) return t("gallery.origin_nominal");
  return t("gallery.origin_other");
}

/* 卡面/抽屉一句话说明：词表 desc 优先；新模板回退 topology 首句清洗
   （剥内部标记 WP2.x/Tier N/#NNN/日期段），无 topology 走诚实缺省行。 */
function cardDesc(c) {
  const k = DESC_KEYS[c.name];
  if (k) return t(k);
  const topo = String(c.topology || "")
    .replace(/（[^）]*）/g, (s) =>
      (/WP\d|Tier|#\d|20\d\d-\d\d|REGISTER|锚/.test(s) ? "" : s))
    .replace(/WP\d+(?:\.\d+)?|Tier\s*\d+|#\d+/g, "");
  const first = topo.split(/[。；;]/)[0].trim();
  return first || t("gallery.desc_missing");
}

/* ═══ 可信度锚对照卡（aurora_i W2-S1，R3 设计 M1；零新端点）══════════
   数据面：/api/anchors 摘要（量名/引擎对/值/门/新鲜度，进页并行预取，
   模块级缓存——重进页即时渲染）+ /api/anchors/{id} 详情逐锚惰性补拉
   （清单摘要面不含 provenance——verdict_state 与证据目录只在详情；
   Map 缓存，失败也缓存空 provenance 不无限重试）。过滤口径：
   engine_pair.referee=hfss（注册表现役 17 条仲裁锚）× template_family
   精确命中或 "*" 通配（注册表语义原样消费，"*" 全局锚全模板可见）。
   呈现红线（#122 家族）：DISAGREE/UNKNOWN/双值指针锚如实渲染，不凑绿
   不隐藏；verdict 态分类只认 DISAGREE/AGREE 字面（DISAGREE 优先——
   长串态内可能并列"AGREE_JUDGE 单项不救总态"字样，先红后绿防误绿），
   其余态（REJUDGE_PASS/BRANCH_A_* 等）原样 token 中性灰呈现。证据目录
   是 runs/ 下纯文本路径（--expose-runs 缺省关，R2-B-05——不渲染链接）。 */
let _anchorList = null;        // /api/anchors 摘要行（进页预取，模块级缓存）
let _anchorLoadFailed = false; // 清单定局失败（诚实降级一行，不重试风暴）
const _anchorProv = new Map(); // anchor_id → provenance（详情惰性补拉缓存）
const _anchorInFlight = new Set(); // 在途详情去重（晚到补铺重铺不重发）
let _drawerCard = null;        // 当前抽屉模板卡（清单/详情晚到时整节重铺用）

function anchorEngineName(e) {
  if (e === "mmt") return t("gallery.engine_mmt");
  return e === "openems" ? "openEMS" : e === "hfss" ? "HFSS" : String(e);
}

function anchorFamilyMatch(fams, name) {
  const arr = Array.isArray(fams) ? fams : (fams == null ? [] : [fams]);
  return arr.indexOf("*") >= 0 || arr.indexOf(name) >= 0;
}

function anchorUnit(u) {
  if (u === "percent") return "%";
  if (u === "dimensionless") return t("gallery.unit_dimensionless");
  return u == null ? "" : String(u);
}

/* verdict 态三分类徽章（AGREE 绿/DISAGREE 红/其余灰——UNKNOWN/其他态
   原样 token，不猜测不归并）。 */
function anchorVerdictOf(state) {
  const s = state == null ? "" : String(state);
  if (!s)
    return { cls: "muted", label: t("gallery.anchor_verdict_unknown"), raw: "" };
  const tok = s.split("（")[0].trim() || s;
  if (/DISAGREE/i.test(s))
    return { cls: "err", label: t("gallery.anchor_verdict_disagree"), raw: tok };
  if (/AGREE/i.test(s))
    return { cls: "ok", label: t("gallery.anchor_verdict_agree"), raw: tok };
  return { cls: "muted", label: tok, raw: tok };
}

/* 进页预取锚清单（幂等：已就绪/已定局即跳过；signal=视图切页收束同款）。 */
function ensureAnchorList(signal) {
  if (_anchorList || _anchorLoadFailed) return;
  apiFetch("/api/anchors", { signal }).then((d) => {
    if (d && d.aborted) return; // UI-R12：切页取消——不写隐藏区
    if (d && d.ok) _anchorList = d.anchors || [];
    else _anchorLoadFailed = true;
    // 清单晚到且抽屉已开：可信度节补铺（用户先点开抽屉的慢网路径）
    if (_drawerEl && _drawerEl.isConnected && _drawerCard) {
      const s2 = _drawerEl.querySelector("[data-slot=credibility]");
      if (s2) renderCredibilityInto(s2, _drawerCard);
    }
  });
}

/* 单锚卡（摘要行 + 已缓存的详情 provenance；数据全部 esc 后插值）。 */
function anchorCardHtml(a) {
  const q = a.quantity || {};
  const ep = a.engine_pair || {};
  const u = a.uncertainty || {};
  const id = String(a.anchor_id);
  const hasProv = _anchorProv.has(id); // 详情已定局（含失败=空 provenance）
  const prov = _anchorProv.get(id);
  // 详情在途=判定读取中（诚实区分"没拉到"与"拉到了但无判定记录"）
  const v = hasProv
    ? anchorVerdictOf(prov ? prov.verdict_state : null)
    : { cls: "muted", label: t("gallery.anchor_verdict_pending"), raw: "" };
  const fams = Array.isArray(a.template_family) ? a.template_family : [];
  const isGlobal = fams.indexOf("*") >= 0;
  const rawTok = v.raw
    ? `<span class='muted' style='font-size:11.5px'>${esc(v.raw)}</span>`
    : "";
  const unitTxt = anchorUnit(q.unit);
  let valLine;
  if (a.value != null) {
    // 量名带 dev 段=引擎对偏差幅度锚；否则=登记常量锚（如实区分两种语义）
    const isDev = /(^|_)dev(_|$)/.test(String(q.name || ""));
    valLine = "<div>" + t(isDev
      ? "gallery.anchor_dev_tpl" : "gallery.anchor_value_tpl",
      { v: esc(fmtVal(a.value)) }) + (unitTxt ? " " + esc(unitTxt) : "") + "</div>";
  } else if (q.values && typeof q.values === "object" &&
             Object.keys(q.values).length) {
    // 双值指针锚（DISAGREE 家族）：openems/hfss 双侧登记值原样并列
    const pairs = Object.keys(q.values)
      .map((k) => esc(k) + "=" + esc(fmtVal(q.values[k]))).join(" | ");
    valLine = "<div>" + t("gallery.anchor_values_tpl", { pairs }) +
      (q.value_unit ? " " + esc(anchorUnit(q.value_unit)) : "") + "</div>";
  } else {
    valLine = `<div class='muted' style='font-size:11.5px'>${esc(t("gallery.anchor_no_single_value"))}</div>`;
  }
  let gateLine = "";
  if (u && u.value != null) {
    const gv = esc(fmtVal(u.value));
    if (u.kind === "arbitration_interval") {
      const usep = unitTxt === "%" ? "" : " ";
      // 登记 note 前缀二分（#122 诚实呈现）：DISAGREE 指针锚的
      // uncertainty.value 是"观测引擎对分裂幅度"不是门——一律标"预声明门"
      // 会把观测值误标成判据。前缀 CJK 走 \u 转义（i18n hardcode 棘轮：
      // 本文件字面量 Han 基线=0；词表侧标签见 anchor_gate/observed_split）。
      // 无 note 或前缀不合→按 kind 缺省语义走"预声明门"（登记面缺省）。
      const note0 = String(u.note || "");
      const isObs = note0.indexOf("\u89c2\u6d4b") === 0; // "观测"
      gateLine = "<div>" + t(isObs
        ? "gallery.anchor_observed_split_tpl"
        : "gallery.anchor_gate_tpl",
        { v: gv, u: usep + esc(unitTxt) }) + "</div>";
    } else if (u.kind === "relative") {
      gateLine = "<div>" + t("gallery.anchor_unc_rel_tpl",
        { p: esc(fmtVal(u.value * 100)) }) + "</div>";
    } else if (u.kind === "engine_pair_spread") {
      gateLine = "<div>" + t("gallery.anchor_unc_spread_tpl", { v: gv }) + "</div>";
    } else {
      gateLine = `<div>${esc(String(u.kind))} ${gv}</div>`;
    }
  }
  const si = a.stale_info || {};
  const ageTxt = si.age_days == null ? "-" : (+si.age_days).toFixed(1);
  const freshTxt = si.stale === true
    ? t("gallery.anchor_age_tpl", { n: ageTxt }) + t("gallery.anchor_stale_flag")
    : si.stale === false ? t("gallery.anchor_age_tpl", { n: ageTxt })
    : t("gallery.anchor_no_date");
  const sem = String(q.semantics || "");
  const semShort = sem.length > 200 ? sem.slice(0, 200) + "…" : sem;
  const runs = prov && Array.isArray(prov.arbitration_runs)
    ? prov.arbitration_runs : [];
  const evLine = runs.length
    ? `<div class='muted' style='font-size:11.5px'>${t("gallery.anchor_evidence_tpl", { ev: esc(runs.join("; ")) })}</div>`
    : "";
  return `<div style='border:1px solid var(--border);border-radius:10px;padding:6px 10px;margin:6px 0'>
    <div style='display:flex;align-items:baseline;gap:6px;flex-wrap:wrap'>
      <code>${esc(String(a.anchor_id))}</code>
      ${T.badge(v.label, v.cls)}${rawTok}
      ${isGlobal ? T.badge(t("gallery.anchor_global"), "muted") : ""}
    </div>
    ${sem ? `<div class='muted' style='font-size:11.5px;margin:6px 0' title='${escAttr(sem)}'>${esc(semShort)}</div>` : ""}
    <div style='font-size:12px;display:flex;flex-direction:column'>${ep.referee ? "<div>" + t("gallery.anchor_pair_tpl", { a: esc(anchorEngineName(ep.calibrated)), r: esc(anchorEngineName(ep.referee)) }) + "</div>" : ""}${valLine}${gateLine}</div>
    <div class='muted' style='font-size:11.5px;margin-top:4px'>${esc(freshTxt)}</div>
    ${evLine}
  </div>`;
}

/* 可信度节渲染（抽屉打开与清单/详情晚到补铺共用单点；三态=加载中/
   加载失败/无匹配诚实行，与卡面参数表/预览段同级纪律）。 */
function renderCredibilityInto(slot, c) {
  if (_anchorLoadFailed) {
    slot.innerHTML = `<div class='muted' style='font-size:11.5px'>${t("gallery.anchor_load_fail")}</div>`;
    return;
  }
  if (!_anchorList) {
    slot.innerHTML = `<div class='muted' style='font-size:11.5px'>${t("gallery.loading")}</div>`;
    return;
  }
  const matched = _anchorList.filter((a) => a && a.engine_pair &&
    a.engine_pair.referee === "hfss" && anchorFamilyMatch(a.template_family, c.name));
  if (!matched.length) {
    slot.innerHTML = `<div class='muted' style='font-size:11.5px'>${t("gallery.anchor_none")}</div>`;
    return;
  }
  slot.innerHTML =
    `<div class='muted' style='font-size:11.5px;margin-bottom:4px'>${t("gallery.anchor_count_tpl", { n: matched.length })}<br>${t("gallery.anchor_legend")}</div>` +
    matched.map(anchorCardHtml).join("");
  const settle = () => {
    if (_drawerEl && _drawerEl.isConnected && _drawerCard &&
        _drawerCard.name === c.name) {
      const s2 = _drawerEl.querySelector("[data-slot=credibility]");
      if (s2) renderCredibilityInto(s2, c);
    }
  };
  for (const a of matched) {
    const id = String(a.anchor_id);
    // 在途/已缓存（含失败定局）都跳过——首条详情到达触发的整节重铺
    // 会对未定局锚重扫，无在途守卫会重复发请求（实测 duple 病理）
    if (_anchorProv.has(id) || _anchorInFlight.has(id)) continue;
    _anchorInFlight.add(id);
    apiFetch("/api/anchors/" + encodeURIComponent(id)).then((d) => {
      _anchorProv.set(id, d && d.ok && d.anchor ? (d.anchor.provenance || {}) : {});
      _anchorInFlight.delete(id);
      settle();
    }).catch(() => {
      _anchorProv.set(id, {});
      _anchorInFlight.delete(id);
      settle();
    });
  }
}

/* ═══ 对照曲线节（W3-S2，R3 设计 M3 前端半）════════════════════════
   双引擎对=叠加图（HFSS 橙/openEMS 蓝+图例+偏差注记）；单引擎=单线+
   note；无数据（含端点未落地/服务端明示无对照/解析空）=整节保持隐藏
   （wrap display:none 缺省，数据定局才揭示——"无数据模板不显示该节"，
   零空壳占位）。偏差注记优先信封 max_deviation，缺席走客户端同频网
   兜底（#294 最近邻口径，cred_curves.js）；频网不齐=诚实"未生成自动
   注记"行（悬停读数可逐点对照）。verdict/sources 原样渲染（esc 通道），
   DISAGREE 不凑绿不隐藏（#122 家族）。 */
async function renderCredCurvesInto(wrap, c) {
  const slot = wrap.querySelector("[data-slot=credcurves]");
  const r = await credFetch(c.name, viewSignal("gallery"));
  // 切页（signal 收束）/抽屉已关（wrap 脱离文档）=不写隐藏区（UI-R12 同款）
  if (r.aborted || !wrap.isConnected) return;
  if (r.status !== "data") return; // 无对照数据：整节保持隐藏
  const v = r.view;
  const series = credSeriesLabeled(v.curves, bodyIsLight());
  const maxDev = v.maxDev || (v.hasPair ? credMaxDev(v.curves) : null);
  let head = "";
  if (v.verdict) {
    // verdict 汇总徽章（#122 先红后绿：DISAGREE 优先判；其余=灰 UNKNOWN）
    const c0 = v.verdict.counts || {};
    const allAgree = c0.total > 0 && c0.agree === c0.total;
    const vd = c0.disagree
      ? { cls: "err", label: t("gallery.anchor_verdict_disagree") }
      : allAgree
      ? { cls: "ok", label: t("gallery.anchor_verdict_agree") }
      : { cls: "muted", label: t("gallery.anchor_verdict_unknown") };
    head = `<div style='display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;margin:var(--space-1) 0 var(--space-1)'>` +
      T.badge(vd.label, vd.cls) +
      `<span class='muted' style='font-size:11.5px'>${esc(t("gallery.cred_verdict_counts_tpl", {
        a: +c0.agree || 0, d: +c0.disagree || 0,
        u: +c0.unknown || 0, n: +c0.total || 0,
      }))}</span></div>`;
  }
  let note;
  if (!v.hasPair) {
    // 单引擎模板：单线+诚实 note（不冒充双引擎对照；服务端 notes 另行
    // 承载 OE 缺席原因，见下方脚注区）
    note = `<div class='muted' style='font-size:11.5px;margin:var(--space-1) 0 var(--space-2)'>` +
      t("gallery.cred_single_note_tpl",
        { e: esc(credEngineTag(v.engines[0] || "unknown")) }) + `</div>`;
  } else if (maxDev) {
    note = `<div style='font-size:12px;margin:var(--space-1) 0 var(--space-2)'>` +
      t("gallery.cred_dev_tpl", {
        name: esc(maxDev.name),
        v: esc((+maxDev.dev).toFixed(2)),
        f: maxDev.freq != null ? esc((+maxDev.freq).toFixed(4)) : "-",
      }) + `</div>`;
  } else {
    note = `<div class='muted' style='font-size:11.5px;margin:var(--space-1) 0 var(--space-2)'>` +
      t("gallery.cred_dev_na") + `</div>`;
  }
  const srcLine = v.sources.length
    ? `<div class='muted' style='font-size:11.5px;margin-top:4px'>` +
      t("gallery.cred_sources_tpl", { s: esc(v.sources.join("; ")) }) + `</div>`
    : "";
  // 服务端 notes（掩码口径/单引擎缺席原因/DISAGREE 预警）原样脚注（esc）
  const notesLine = v.notes.length
    ? `<div class='muted' style='font-size:11.5px;margin-top:4px'>` +
      v.notes.map((x) => esc(x)).join("<br>") + `</div>`
    : "";
  wrap.style.display = ""; // 数据定局才揭示（无数据模板整节不可见）
  slot.innerHTML = head + note +
    `<div id='gal-cred-chart'></div>` +
    `<div class='muted' style='font-size:11.5px;margin-top:var(--space-1)'>${t("gallery.cred_legend")}</div>` +
    srcLine + notesLine;
  T.plotCard(T.$("gal-cred-chart"), {
    series,
    xlabel: "GHz", ylabel: "dB",
    height: "300px", zoom: true, crosshair: true,
    exportName: "cred-curves-" + c.name.replace(/\W/g, "-"),
  });
}

export async function pageGallery() {
  const v = T.$("view-gallery");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("gallery.help_1")}</li>
      <li>${t("gallery.help_2")}</li>
      <li>${t("gallery.help_3")}</li>`) +
    `<h2 class='page'><span data-i18n='gallery.title'>${t("gallery.title")}</span> <small data-i18n='gallery.subtitle'>${t("gallery.subtitle")}</small></h2>
     <div class='toolbar'><input id='gal-filter' size='24' placeholder='${t("gallery.filter_placeholder")}' data-i18n-ph='gallery.filter_placeholder'>
       <span id='gal-count' class='muted'></span></div>
     <div id='gal-grid' class='muted'>${t("gallery.loading")}</div>`;
  applyI18nRoot(v); // 壳静态标签首扫（W1-S2）
  ensureAnchorList(viewSignal("gallery")); // 可信度锚清单并行预取（W2-S1）
  const d = await apiFetch("/api/gallery", { signal: viewSignal("gallery") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const grid = T.$("gal-grid");
  if (!d.ok) {
    // 三态收敛（aurora_f W2-S5，R1 #8 批1）：加载失败=kitErrorPanel 带重试
    //（重试=整页重进，pageGallery 幂等：壳判 innerHTML 已在即跳过）
    grid.innerHTML = kitErrorPanel((d.errors || []).join("; "), "gal-retry");
    const rb = T.$("gal-retry");
    if (rb) rb.onclick = () => pageGallery();
    return;
  }
  _galCards = d.cards || [];
  T.$("gal-count").textContent = t("gallery.count_tpl", { n: d.n_templates, p: d.n_previews });
  const render = () => {
    const ft = T.$("gal-filter").value.trim().toLowerCase();
    const rows = _galCards.filter((c) => !ft ||
      `${c.name} ${c.topology || ""}`.toLowerCase().includes(ft));
    if (!rows.length) {
      // 三态收敛（R1 #8 批1）：过滤零命中=kitEmptyState（文案 t() 渲染期烘焙）
      grid.innerHTML = kitEmptyState(t("gallery.empty_filter"));
      return;
    }
    // R2 卡面瘦身：一句人话说明 + 详情钮（参数串折叠进抽屉）；"未配
    // 预览通道"降为卡角小标记，不再满屏徽标（诚实行在抽屉内）。
    grid.innerHTML = `<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(21rem,1fr));gap:10px'>` +
      rows.map((c) => `<div class='panel' style='margin:0'>
        <div style='display:flex;align-items:baseline;gap:6px;flex-wrap:wrap'>
          <b>${esc(c.name)}</b>
          ${c.f0_ghz ? `<span class='badge muted'>f0 ${esc(c.f0_ghz)} GHz</span>` : ""}
          <span style='flex:1'></span>
          ${c.preview ? T.badge(t("gallery.preview_badge"), "ok") : `<span class='muted' style='font-size:var(--text-xs)'>${t("gallery.no_preview")}</span>`}
        </div>
        <div class='muted' style='font-size:11.5px;margin:var(--space-1) 0'>${esc(cardDesc(c))}</div>
        <button class='minor' style='margin-top:6px' data-gal='${escAttr(c.name)}'>${t("gallery.detail_btn")}</button>
      </div>`).join("") + `</div>`;
    for (const btn of grid.querySelectorAll("[data-gal]"))
      btn.onclick = () => openDrawer(btn.getAttribute("data-gal"));
  };
  T.$("gal-filter").oninput = render;

  /* ═══ 详情抽屉（R2）：全部 72 卡可点开 ═══════════════════════════
     五段=①人话说明（+结构口径次行）②参数白话表（含义/名义值/来源）
     ③可信度锚对照卡（W2-S1：HFSS 仲裁锚按族渲染）④对照曲线（W3-S2：
     双引擎叠加图，无数据整节隐藏）⑤预览段（有通道=滑块+闭式计算搬入
     抽屉；无通道=诚实一行）。
     形态=kitConfirm 同款 fixed 遮罩+z-modal 令牌（filebrowser 先例）；
     关闭=按钮/遮罩/Esc 三通道，开新先关旧（单例）。 */
  function closeDrawer() {
    if (_drawerEl) {
      if (_drawerKeyHandler)
        document.removeEventListener("keydown", _drawerKeyHandler, true);
      _drawerKeyHandler = null;
      _drawerEl.remove();
      _drawerEl = null;
    }
    _drawerCard = null; // 可信度节晚到补铺的挂卡引用随抽屉同生命周期
  }
  function openDrawer(name) {
    const c = _galCards && _galCards.find((x) => x.name === name);
    if (!c) return;
    closeDrawer();
    const semMap = parseSemantics(String(c.param_semantics || ""), c.params || []);
    const ports = c.n_ports; // 裸 API 插值豁免面收敛：局部量承担 badge 分支
    const rows = orderedParams(c).map((k) => {
      const meaning = semMap[k] ||
        (GLOSS_KEYS[k] ? t(GLOSS_KEYS[k]) : t("gallery.sem_missing"));
      return `<tr><td><code>${esc(k)}</code></td><td>${esc(meaning)}</td>` +
        `<td>${esc(fmtVal((c.nominal_params || {})[k]))}</td>` +
        `<td>${esc(paramOrigin(c, k))}</td></tr>`;
    }).join("");
    const ov = document.createElement("div");
    ov.className = "kit-confirm";
    ov.setAttribute("role", "dialog");
    ov.setAttribute("aria-modal", "true");
    ov.setAttribute("aria-label",
      t("gallery.detail_aria_tpl", { name: c.name }));
    // kitConfirm 同款令牌（z-modal/backdrop-dim，filebrowser a11y 先例）
    ov.style.cssText = "position:fixed;inset:0;background:var(--backdrop-dim);z-index:var(--z-modal);display:flex;align-items:center;justify-content:center";
    ov.innerHTML = `<div class='panel' style='max-width:46rem;width:min(92vw,46rem);max-height:86vh;overflow:auto;margin:0'>
      <div style='display:flex;align-items:baseline;gap:8px;flex-wrap:wrap'>
        <b class='title' style='font-size:1.05rem'>${esc(c.name)}</b>
        ${c.f0_ghz ? `<span class='badge muted'>f0 ${esc(c.f0_ghz)} GHz</span>` : ""}
        ${ports ? `<span class='badge muted'>${t("gallery.ports_tpl", { n: ports })}</span>` : ""}
        <span style='flex:1'></span>
        <button class='minor' data-act='close'>${t("gallery.close")}</button>
      </div>
      <p style='margin:var(--space-2) 0 0'>${esc(cardDesc(c))}</p>
      ${c.topology ? `<div class='muted' style='font-size:11.5px;margin-top:var(--space-1)'><b>${t("gallery.drawer_topology")}</b> ${esc(c.topology)}</div>` : ""}
      <h3 style='margin:var(--space-3) 0 var(--space-1)'>${t("gallery.drawer_params")}</h3>
      <table><thead><tr><th scope='col'>${t("gallery.th_param")}</th><th scope='col'>${t("gallery.th_mean")}</th><th scope='col'>${t("gallery.th_value")}</th><th scope='col'>${t("gallery.th_origin")}</th></tr></thead><tbody>${rows}</tbody></table>
      <h3 style='margin:var(--space-3) 0 var(--space-1)'>${t("gallery.drawer_credibility")}</h3>
      <div data-slot='credibility'></div>
      <div data-slot='credcurves-wrap' style='display:none'>
        <h3 style='margin:var(--space-3) 0 var(--space-1)'>${t("gallery.cred_title")}</h3>
        <div data-slot='credcurves'></div>
      </div>
      <h3 style='margin:var(--space-3) 0 var(--space-1)'>${t("gallery.drawer_preview")}</h3>
      <div data-slot='preview'></div>
    </div>`;
    document.body.appendChild(ov);
    _drawerEl = ov;
    _drawerCard = c;
    _drawerKeyHandler = (e) => { if (e.key === "Escape") closeDrawer(); };
    document.addEventListener("keydown", _drawerKeyHandler, true);
    ov.querySelector("[data-act=close]").onclick = closeDrawer;
    ov.onclick = (e) => { if (e.target === ov) closeDrawer(); };
    renderCredibilityInto(ov.querySelector("[data-slot=credibility]"), c);
    renderCredCurvesInto(ov.querySelector("[data-slot=credcurves-wrap]"), c);
    renderPreviewInto(ov.querySelector("[data-slot=preview]"), c);
    const fb = ov.querySelector("[data-act=close]");
    if (fb && fb.focus) fb.focus();
  }

  /* 预览段（原 openPreview 逻辑搬入抽屉；信封消费形态逐键不变）。 */
  function renderPreviewInto(slot, c) {
    const p = c && c.preview;
    if (!p) {
      // 诚实边界（R2）：无预览通道模板不再显示徽标，抽屉内一行说清
      slot.innerHTML = `<div class='muted' style='font-size:11.5px'>${t("gallery.preview_uncovered")}</div>`;
      return;
    }
    const meta = p.slider_meta || {};
    const params = { ...p.params };
    const key = (s) => String(s).replace(/\W/g, "_"); // pg-s-* 惯例 id 消毒（UI-R11 P2-7）
    slot.innerHTML = `<div class='muted' style='font-size:var(--text-xs);margin-bottom:var(--space-1)'><code>${esc(p.calculator)}</code></div>
      <div data-slot='sliders' style='margin:var(--space-2) 0'></div>
      <div class='toolbar'><button class='primary' data-act='run'>${t("gallery.compute")}</button>
        <span data-slot='msg' class='muted'></span></div>
      <div data-slot='result' class='muted' style='margin-top:var(--space-2)'>${t("gallery.result_hint")}</div>`;
    const sliders = slot.querySelector("[data-slot=sliders]");
    sliders.innerHTML = (p.sliders || []).map((k) => {
      const m = meta[k] || { min: params[k] * 0.5, max: params[k] * 1.5, step: Math.abs(params[k]) / 100, initial: params[k] };
      return `<label style='display:block;margin:6px 0'><b>${esc(k)}</b> <span data-slot='v' data-k='${escAttr(k)}'>${(+m.initial).toPrecision(6)}</span>
        <input id='gal-s-${key(k)}' type='range' data-k='${escAttr(k)}' min='${m.min}' max='${m.max}' step='${m.step}' value='${m.initial}' style='width:100%'></label>`;
    }).join("") || "<span class='muted'>" + t("gallery.no_sliders") + "</span>";
    for (const input of sliders.querySelectorAll("input[type=range]"))
      input.oninput = () => {
        params[input.getAttribute("data-k")] = Number(input.value);
        const show = sliders.querySelector(
          "span[data-slot=v][data-k='" + input.getAttribute("data-k") + "']");
        if (show) show.textContent = (+input.value).toPrecision(6);
      };
    slot.querySelector("[data-act=run]").onclick = async () => {
      slot.querySelector("[data-slot=msg]").textContent = t("gallery.computing");
      const r = await apiFetch("/api/calculators/run", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: p.calculator, params }),
        timeoutMs: 0 }); // 长跑豁免（P9-11 缺省超时）：计算器真算时长不定
      slot.querySelector("[data-slot=msg]").textContent = "";
      const el = slot.querySelector("[data-slot=result]");
      // 三态收敛（R1 #8 批1）：闭式计算失败=kitErrorPanel（原裸 ✗ span，
      // 形态②清偿；重触发=「计算」钮，不加重试钮防双发）
      if (!r.ok) { el.innerHTML = kitErrorPanel(r.error || (r.errors || []).join("; ")); return; }
      el.innerHTML = "<table><tbody>" + Object.entries(r.result || r)
        .filter(([k]) => k !== "ok")
        .map(([k, x]) => `<tr><td><b>${esc(k)}</b></td><td>${esc(typeof x === "object" ? JSON.stringify(x) : String(x))}</td></tr>`).join("")
        + "</tbody></table>";
    };
  }
  render();
}

/* ═══ R-1（aurora_e W3-S12）：PageContext 增量钩子 galleryCtx ═══════════
   refresh=模板卡数据重拉（pageGallery 幂等：壳判 innerHTML 已在即跳过，
   /api/gallery 重拉后按当前过滤词重铺网格；过滤输入值保持，抽屉单例随
   重拉保留——数据面重拉不碰 DOM 弹层）。无轮询面，leave 不需要。 */
export const galleryCtx = {
  refresh: () => pageGallery(),
};
