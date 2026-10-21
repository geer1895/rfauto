/* rfauto 模板画廊页（aurora_d UI-R2 自 pages.js 拆出，PR-5）。
   R2 人性化改造席（用户实测批次 2026-10-19）：72 卡全量详情抽屉——
   ①一句话人话说明（gallery.desc_* 词表，缺席回退 topology 首句清洗）
   ②参数白话表（param_semantics 前端解析 + 附加键白话兜底 + 数值来源列）
   ③有预览通道才显示闭式预览，没有的显示诚实一行（不再满屏"未配通道"
   徽标，卡角仅留小标记）。卡面瘦身：参数串折叠进抽屉。
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
     三段=①人话说明（+结构口径次行）②参数白话表（含义/名义值/来源）
     ③预览段（有通道=滑块+闭式计算搬入抽屉；无通道=诚实一行）。
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
      <h3 style='margin:var(--space-3) 0 var(--space-1)'>${t("gallery.drawer_preview")}</h3>
      <div data-slot='preview'></div>
    </div>`;
    document.body.appendChild(ov);
    _drawerEl = ov;
    _drawerKeyHandler = (e) => { if (e.key === "Escape") closeDrawer(); };
    document.addEventListener("keydown", _drawerKeyHandler, true);
    ov.querySelector("[data-act=close]").onclick = closeDrawer;
    ov.onclick = (e) => { if (e.target === ov) closeDrawer(); };
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
