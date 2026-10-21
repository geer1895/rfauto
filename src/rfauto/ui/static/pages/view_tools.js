/* rfauto 微波工具箱页（架构批 UI-R2 自 pages.js 拆出，逐字节搬移）：
   计算器分组/搜索/深链（A2-B）+ 结果可视化/扫参/公式面板（A3-A）。
   数值只在确定性内核（规则 7）：本模块零物理数字产生。
   i18n（架构批 W2-S1 批 4，R1 §面2 P9-5）：chrome 文案余量全迁词表
   （tools.* 键域，zh 与旧字面逐字节同、en 新增）——help 块分段 t()；
   组名=展示层翻译（协议标识符仍以中文单源对齐 API c.group，显示经
   GROUP_I18N 映射、服务端未知组回退原文）；计算器中文名/用途兜底表
   词表化（tools.cn_ 键/cp_ 键，键尾=注册表 name；calcZhName locale 感知，
   en 档兜底显示英文名——API description 中文前缀仍优先，数据面照旧）；
   随数据重建的容器零 data-i18n（头注纪律），API 数据照旧走 esc/escAttr。
   架构批 W4-S1 半程收尾：壳模板兜底字面改 t() 烘焙（data.js 先例，
   zh 档渲染逐字节不变）、扫参选择器 aria 迁词表、组序表改回退表下标
   引用（协议名单源化，序表不再复写中文字面）——本文件残余 CJK 字面量
   仅剩组协议标识符（TOOL_GROUP_FALLBACK 组名 + 实验/其他两常量，与
   core/calc_families/registry.py CALC_GROUP_TABLE 字节对齐的协议单源，
   i18n 棘轮账本"刻意保留"口径，非文案）。 */

import { HEAT_BAND, THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import { _isoRenderers, bindChartResize, echartsInitCached, plotCardCached } from "./charts.js";
import { T, getActiveView } from "./context.js";
import { esc, escAttr, errorText, help } from "./dom.js";
// i18n（架构批 W1-S2 试点页 1；批 4 余量全迁）：壳静态标签 data-i18n+首扫；
// 随数据重建的容器（#tool-desc/#tool-params/#tool-result）文案一律 t() 渲染
// 期烘焙——data-i18n 重扫会覆写动态状态（i18n.js 头注纪律）。
import { t, applyI18nRoot } from "./i18n.js";
import { kitErrorPanel, kitTable } from "./kit.js";
import { showPage } from "./router.js";
// P8-9（架构批 W4-S13，R1 §面4）：T.api→apiFetch 统一请求层（本页 3 点）——
// 数据面（计算器清单）接 viewSignal("tools") 切页收束 + aborted 短路；动作面
// （计算/扫参 POST，扫参逐点串行 await）保持无 signal（用户动作不被切页取消）。
// 信封消费形态逐键不变。
import { apiFetch, viewSignal } from "./api.js";

/* ═══ 微波工具箱（E4 计算器：数值只在确定性内核）═══ */

/* 计算器中文名/用途兜底表 → 词表化（批 4；原 CALC_ZH 字面同笔迁
   pages/i18n.js 的 tools.cn_ 键/tools.cp_ 键，zh 值逐字节不变）：describe() 的
   description 正常以 "中文名：用途" 开头（API 数据面，不经词表），此表只在
   description 缺中文/用途段时经 t() 兜底；en 档显示英文名。键=注册表 name，
   值=[名键, 用途键]。 */
const CALC_KEYS = {
  attenuator_bridged_t: ["tools.cn_attenuator_bridged_t", "tools.cp_attenuator_bridged_t"],
  attenuator_pi: ["tools.cn_attenuator_pi", "tools.cp_attenuator_pi"],
  attenuator_t: ["tools.cn_attenuator_t", "tools.cp_attenuator_t"],
  cavity_perturbation_shift: ["tools.cn_cavity_perturbation_shift", "tools.cp_cavity_perturbation_shift"],
  chebyshev_prototype: ["tools.cn_chebyshev_prototype", "tools.cp_chebyshev_prototype"],
  chebyshev_prototype_asym: ["tools.cn_chebyshev_prototype_asym", "tools.cp_chebyshev_prototype_asym"],
  chebyshev_refl_fn: ["tools.cn_chebyshev_refl_fn", "tools.cp_chebyshev_refl_fn"],
  coupling_matrix_arrow: ["tools.cn_coupling_matrix_arrow", "tools.cp_coupling_matrix_arrow"],
  coupling_matrix_extract: ["tools.cn_coupling_matrix_extract", "tools.cp_coupling_matrix_extract"],
  coupling_matrix_folded: ["tools.cn_coupling_matrix_folded", "tools.cp_coupling_matrix_folded"],
  coupling_matrix_response: ["tools.cn_coupling_matrix_response", "tools.cp_coupling_matrix_response"],
  coupling_matrix_synthesize_explicit: ["tools.cn_coupling_matrix_synthesize_explicit", "tools.cp_coupling_matrix_synthesize_explicit"],
  coupling_matrix_synthesize_n2: ["tools.cn_coupling_matrix_synthesize_n2", "tools.cp_coupling_matrix_synthesize_n2"],
  cps_analysis: ["tools.cn_cps_analysis", "tools.cp_cps_analysis"],
  cps_synthesis: ["tools.cn_cps_synthesis", "tools.cp_cps_synthesis"],
  cpw_analysis: ["tools.cn_cpw_analysis", "tools.cp_cpw_analysis"],
  cpw_synthesis: ["tools.cn_cpw_synthesis", "tools.cp_cpw_synthesis"],
  cpwg_analysis: ["tools.cn_cpwg_analysis", "tools.cp_cpwg_analysis"],
  cpwg_synthesis: ["tools.cn_cpwg_synthesis", "tools.cp_cpwg_synthesis"],
  ecss_multipactor_fd: ["tools.cn_ecss_multipactor_fd", "tools.cp_ecss_multipactor_fd"],
  ipc2152_trace_temp_rise: ["tools.cn_ipc2152_trace_temp_rise", "tools.cp_ipc2152_trace_temp_rise"],
  microstrip_analysis: ["tools.cn_microstrip_analysis", "tools.cp_microstrip_analysis"],
  microstrip_lambda_g: ["tools.cn_microstrip_lambda_g", "tools.cp_microstrip_lambda_g"],
  microstrip_loss_heat: ["tools.cn_microstrip_loss_heat", "tools.cp_microstrip_loss_heat"],
  microstrip_synthesis: ["tools.cn_microstrip_synthesis", "tools.cp_microstrip_synthesis"],
  parallel_plate_breakdown_margin: ["tools.cn_parallel_plate_breakdown_margin", "tools.cp_parallel_plate_breakdown_margin"],
  patch_f0_symbolic_e13: ["tools.cn_patch_f0_symbolic_e13", "tools.cp_patch_f0_symbolic_e13"],
  patch_length: ["tools.cn_patch_length", "tools.cp_patch_length"],
  quarter_wave_transformer: ["tools.cn_quarter_wave_transformer", "tools.cp_quarter_wave_transformer"],
  resonator_thermal_drift: ["tools.cn_resonator_thermal_drift", "tools.cp_resonator_thermal_drift"],
  stripline_analysis: ["tools.cn_stripline_analysis", "tools.cp_stripline_analysis"],
  stripline_synthesis: ["tools.cn_stripline_synthesis", "tools.cp_stripline_synthesis"],
  suspended_stripline_analysis: ["tools.cn_suspended_stripline_analysis", "tools.cp_suspended_stripline_analysis"],
  suspended_stripline_synthesis: ["tools.cn_suspended_stripline_synthesis", "tools.cp_suspended_stripline_synthesis"],
  thermal_resistance_stack: ["tools.cn_thermal_resistance_stack", "tools.cp_thermal_resistance_stack"],
  vswr_convert: ["tools.cn_vswr_convert", "tools.cp_vswr_convert"],
};
const _HAS_CJK = /[\u4e00-\u9fff]/;

/* 计算器名：优先 description 冒号前缀（注册表自带中文，API 数据面两档同
   显示）；否则经 t() 查词表兜底（zh=旧 CALC_ZH 名逐字节同，en=英文名），
   再退 key */
function calcZhName(c) {
  const head = String(c.description || "").split(/[：:]/)[0].trim();
  if (head && _HAS_CJK.test(head) && head.length <= 24) return head;
  const keys = CALC_KEYS[c.name];
  return keys ? t(keys[0]) : c.name;
}
/* 参数说明 "类型 单位 中文说明" → {unit, text}；单位 "-" 视为无量纲 */
function parseParamDesc(desc) {
  const t = String(desc || "").trim().split(/\s+/);
  if (t.length >= 3 && /^(float|int|str|bool|list|dict)$/i.test(t[0])) {
    return { unit: t[1] === "-" ? "" : t[1], text: t.slice(2).join(" ") };
  }
  return { unit: "", text: String(desc || "") };
}

/* ── 架构批 A2-B：工具箱分组+搜索选择器与 #/tools/<key> 深链（R5 审计 §②§⑤§⑥）──
   契约：/api/calculators 每键带 group 字段（A2-A 席并行落地）——本席只消费
   c.group；字段缺席时回退"实验态→键名前缀粗映射→其他"，页面不炸。回退表刻意
   粗粒度（键名前缀，不复刻 133 键全表）——group 字段落地后回退仅剩兜底义。
   组名=协议标识符（中文单源，与 API c.group 对齐）；行元素 2=展示层翻译键
   （tools.group_*，批 4），显示经 grpDisp()（未知组名回退原文）。 */
const TOOL_GROUP_FALLBACK = [
  ["EMC·安规·放电", "tools.group_emc", /^(conducted_|radiated_|esd_|exposure_|shielding_|corona_|multipactor_|ecss_)/],
  ["热·功率·可靠性", "tools.group_thermal", /^(thermal_|ipc2152_|microstrip_loss_heat|resonator_thermal_|electromigration_|parallel_plate_|microwave_process_|multimode_cavity_|single_mode_|form_beta_)/],
  ["测量与校准", "tools.group_metrol", /^(power_cal_|trl_|tnvna_|allan_)/],
  ["超材料·超表面", "tools.group_metam", /^(homog_|retrieve_|srr_|wire_media_|crlh_|gstc_)/],
  ["量子读出", "tools.group_quantum", /^qubit_/],
  ["调制与数字链路", "tools.group_mod", /^(modulation_|required_ebn0|coded_ber_|cdr_)/],
  ["天线与阵列", "tools.group_antenna", /^(array\.|cma_)/],
  ["DOA 与波束形成", "tools.group_doa", /^doa_/],
  ["MIMO 与 RIS", "tools.group_mimo", /^(mimo_|ris_)/],
  ["雷达", "tools.group_radar", /^(radar_|albersheim_|ca_cfar_)/],
  ["链路与传播", "tools.group_link", /^(sat_|gt_ratio|rfid_|chipless_|hata_|two_ray_|knife_edge_|rain_|gaseous_|availability_|fade_)/],
  ["收发链路·频综", "tools.group_xcvr", /^(cascade_budget|correlated_cascade_|blocking_|spur_|if_plan_|iq_|phase_noise_|pll_|doherty_)/],
  ["滤波器与耦合矩阵", "tools.group_filter", /^(chebyshev_|coupling_matrix_|cm_|q_factor_|qe_|mask_|cat_|k_split)/],
  ["谐振器与腔体", "tools.group_resonator", /^(coaxial_cavity_|combline_|cavity_|patch_length)/],
  ["匹配·功分·衰减·耦合", "tools.group_match", /^(attenuator_|quarter_wave_|t_match_|klopfenstein_|vswr_|unequal_split_|bethe_|balanced_pair_)/],
  ["传输线正反解", "tools.group_txlines", /^(microstrip|cpw|cpwg|cps|stripline|suspended_stripline|slotline|siw)_/],
];
/* 组序（R5 §② 建议）：常用在前；实验/其他恒殿后；未知组名（服务端新增组）
   按 zh 序排在已知组之后、殿后组之前。组序表按回退表下标引用（W4-S1 i18n
   半程收尾：协议名单源=TOOL_GROUP_FALLBACK，序表不再复写中文字面——两表
   字节漂移在构造上不可能）。 */
const TOOL_GROUP_ORDER_IDX = [15, 14, 12, 13, 6, 7, 8, 9, 10, 11, 5, 0, 1, 2, 3, 4];
const TOOL_GROUP_ORDER = TOOL_GROUP_ORDER_IDX.map((i) => TOOL_GROUP_FALLBACK[i][0]);
const TOOL_GROUP_EXPERIMENTAL = "实验";
const TOOL_GROUP_OTHER = "其他";
/* 组名→词表键映射（批 4）：回退表折叠 + 实验/其他两常量；grpDisp 为组名
   唯一显示口（optgroup 标签/徽章/帮助组清单三处）。 */
const GROUP_I18N = Object.fromEntries(TOOL_GROUP_FALLBACK.map(([g, k]) => [g, k]));
GROUP_I18N[TOOL_GROUP_EXPERIMENTAL] = "tools.group_experimental";
GROUP_I18N[TOOL_GROUP_OTHER] = "tools.group_other";
function grpDisp(g) {
  const k = GROUP_I18N[g];
  return k ? t(k) : g;
}

/* 组归属单源（纯函数，node 行为钉可测）：API group 字段优先；缺字段/空值
   回退 实验态→前缀粗映射→"其他"。 */
export function calcGroup(c) {
  if (c && typeof c.group === "string" && c.group.trim()) return c.group.trim();
  if (c && c.experimental) return TOOL_GROUP_EXPERIMENTAL;
  const name = String((c && c.name) || "");
  for (const [g, , re] of TOOL_GROUP_FALLBACK) if (re.test(name)) return g;
  return TOOL_GROUP_OTHER;
}

/* 分组装配（纯函数）：已知组按 TOOL_GROUP_ORDER，未知组 zh 序跟随，
   实验/其他殿后；组内保持 API 传入序（键名字典序）。 */
export function groupCalcList(list) {
  const buckets = new Map();
  for (const c of list || []) {
    const g = calcGroup(c);
    if (!buckets.has(g)) buckets.set(g, []);
    buckets.get(g).push(c);
  }
  const head = TOOL_GROUP_ORDER.filter((g) => buckets.has(g));
  const mid = [...buckets.keys()]
    .filter((g) => g !== TOOL_GROUP_OTHER && g !== TOOL_GROUP_EXPERIMENTAL &&
      !TOOL_GROUP_ORDER.includes(g))
    .sort((a, b) => a.localeCompare(b, "zh"));
  const tail = [TOOL_GROUP_EXPERIMENTAL, TOOL_GROUP_OTHER]
    .filter((g) => buckets.has(g));
  return [...head, ...mid, ...tail].map((g) => ({ group: g, items: buckets.get(g) }));
}

/* 搜索过滤（纯函数）：键名/中文名/用途三字段子串匹配（大小写不敏感）。 */
export function toolFilterMatch(c, q) {
  const needle = String(q || "").trim().toLowerCase();
  if (!needle) return true;
  return (
    String((c && c.name) || "").toLowerCase().includes(needle) ||
    String(calcZhName(c || {}) || "").toLowerCase().includes(needle) ||
    String((c && c.description) || "").toLowerCase().includes(needle));
}

/* 深链解析（纯函数）："#/tools/<key>" → key；页级 "#/tools" 等其余 → null。
   decodeURIComponent 对非法序列会抛——守卫后原样返回。 */
export function toolsDeepLinkKey(hash) {
  const m = String(hash || "").match(/^#\/tools\/(.+)$/);
  if (!m) return null;
  try { return decodeURIComponent(m[1]); } catch { return m[1]; }
}

/* 深链/命令面板入口（导出给 app.js 席与 palette 类调用方）：选中某计算器。
   tools 页在前台且选择器在手 → 原地选中（零重取）；否则记待选 key 拉起
   tools 页（pageTools 渲染完成后消费，location.hash 兜底双保险）。 */
const _toolsUI = { sel: null, cals: [], renderParams: null };
let _toolsPendingKey = null;
export function toolsSelectKey(key) {
  key = String(key || "");
  if (getActiveView() === "tools" && _toolsUI.sel &&
      _toolsUI.cals.some((c) => c.name === key)) {
    _toolsUI.sel.value = key;
    if (_toolsUI.renderParams) _toolsUI.renderParams();
    return;
  }
  _toolsPendingKey = key;
  showPage("tools");
}

/* hashchange 单源监听（initPages 装配一次，幂等 + node import 零 DOM 依赖）：
   架构批 A4-C 起收编为全站唯一 hashchange 监听——旧 app.js 页级 _applyHash
   监听与本席 tools key 级自查双监听并存，两级路由落地后归一：事件经宿主注入
   的 T.routeDispatch（app.js 两级分发器，页级+参数级都在其上）回注；宿主
   缺席（独立加载）时回退本席 tools 自查（旧行为保全）。 */
let _toolsDeepLinkBound = false;
export function _bindToolsDeepLink() {
  if (_toolsDeepLinkBound || typeof window === "undefined" || !window.addEventListener) return;
  _toolsDeepLinkBound = true;
  window.addEventListener("hashchange", () => {
    if (T.routeDispatch) { T.routeDispatch(); return; }
    const key = toolsDeepLinkKey(location.hash);
    if (key) toolsSelectKey(key);
  });
  // 初次载入兜底（双保险）：boot 期宿主 _applyHash 已消费参数深链则幂等跳过
  // （_activeView 已是 tools）；仅宿主分发缺席时由本席 setTimeout 补拉一次。
  if (toolsDeepLinkKey(location.hash)) {
    setTimeout(() => {
      const key = toolsDeepLinkKey(location.hash);
      if (key && getActiveView() !== "tools") toolsSelectKey(key);
    }, 0);
  }
}

/* 工具箱页局部样式（页自注入，不动 index.html——席位文件面隔离）：
   参数表淡入 + 尊重系统"减少动态效果"设置 + 架构批 A3-A 公式面板/扫参
   面样式。幂等：按 id 只注入一次。 */
function _ensureToolsStyle() {
  if (document.getElementById("tools-page-style")) return;
  const st = document.createElement("style");
  st.id = "tools-page-style";
  st.textContent =
    "@keyframes toolFade{from{opacity:0;transform:translateY(4px)}" +
    "to{opacity:1;transform:none}}" +
    ".tool-fade{animation:toolFade .22s ease}" +
    "@media (prefers-reduced-motion:reduce){.tool-fade{animation:none}}" +
    // A3-A 公式面板：等宽 pre（description 全文，公式/出处原文可复制）
    ".tool-formula summary{cursor:pointer;color:var(--accent);margin-top:6px}" +
    ".tool-formula pre{white-space:pre-wrap;font-family:ui-monospace," +
    "SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;line-height:1.5;" +
    "margin:6px 0 0;padding:var(--space-2);border:1px solid var(--border);" +
    "border-radius:var(--radius-xs);color:var(--fg);max-height:260px;overflow:auto}";
  document.head.appendChild(st);
}

/* ═══ 架构批 A3-A：工具箱结果可视化 + 扫参 + 公式面板（R5 审计 §③§④§⑤）═══
   通用启发式（零 service 改动，数值语义全由注册表键名自述）：
   - x-y 曲线：结果 dict 中"轴名键的 num_list"判 x（R5 §③ 命名清单），
     其余等长非轴 num_list 判 y 系列；嵌套值对象 {x:[...],y:[...]} 形态
     递归一层；dict_list 每项含等长 num_list 的系列族（圆柱腔模式图）。
   - 矩阵热图：列表的等长列表——复数方阵（[re,im] 对，耦合矩阵/gstc 家族）
     取模渲染；普通数值矩阵列 ≥3 才判（列 <3 更像点对列表，不硬猜）。
   - 识别不了的形态如实降级为 JSON 键值表（数据诚实，不硬猜）。 */

/* 轴名判别：键名分段命中 R5 §③ x 轴命名清单（freq/theta/tau/ebn0/pbo/
   t_grid/electric/omega/aspect/time/x）才可作 x 轴——分段锚定（^|_…_|$）
   防 "box"/"max" 类误命中。 */
const _TOOL_AXIS_RE = /(^|_)(x|freq|theta|tau|ebn0|pbo|t_grid|electric|omega|aspect|time)(_|$)/i;
const _TOOL_XLOG_RE = /(^|_)(freq|tau)(_|$)/i; // 频率/τ 跨量级 → log x（全正才生效）
const _TOOL_YLOG_RE = /(^|_)(ber|adev)(_|$)/i; // BER/ADEV 跨量级 → log y（全系列全正才生效）
const _TOOL_CHART_CAP = 4; // 单结果最多画 4 张图（防病态结果刷屏）
const _TOOL_SERIES_CAP = 12; // 单图最多 12 系列（模式图 8 系列实测在内）

/* 纯函数：数值数组判别（全有限数值、长度 ≥minLen）——探测器地基。 */
export function toolIsNumList(v, minLen = 2) {
  return Array.isArray(v) && v.length >= minLen &&
    v.every((x) => typeof x === "number" && Number.isFinite(x));
}

/* 纯函数（node 行为钉可测）：x-y 曲线探测。返回
   [{title, xKey, x, series:[{name, y}]}]，识别不了返回 []（调用方如实降级）。 */
export function toolDetectCurves(result) {
  const out = [];
  if (!result || typeof result !== "object" || Array.isArray(result)) return out;
  const entries = Object.entries(result);
  // ① 平铺：轴名 num_list 为 x；其余等长、非轴名 num_list 为系列
  //   （轴名 num_list 不当系列——coupling_matrix_response 的 omega_norm 不进图例）
  const xEnt = entries.find(([k, v]) => toolIsNumList(v) && _TOOL_AXIS_RE.test(k));
  if (xEnt) {
    const xKey = xEnt[0];
    const series = entries
      .filter(([k, v]) => k !== xKey && !_TOOL_AXIS_RE.test(k) &&
        toolIsNumList(v) && v.length === xEnt[1].length)
      .map(([k, v]) => ({ name: k, y: v }));
    if (series.length) {
      out.push({ title: t("tools.curve_title_tpl", { x: xKey }), xKey, x: xEnt[1], series: series.slice(0, _TOOL_SERIES_CAP) });
    } else {
      // ③ 系列族：dict_list 每项含与 x 等长的 num_list（如圆柱腔模式图
      //   series[].f_norm；系列名取项内字符串字段 mode/name/key）
      const fam = [];
      for (const [k, v] of entries) {
        if (!Array.isArray(v) || !v.length) continue;
        if (!v.every((it) => it && typeof it === "object" && !Array.isArray(it))) continue;
        for (let i = 0; i < v.length && fam.length < _TOOL_SERIES_CAP; i++) {
          const it = v[i];
          const nmf = ["mode", "name", "key"].find((f) => typeof it[f] === "string");
          for (const [kk, vv] of Object.entries(it)) {
            if (toolIsNumList(vv) && vv.length === xEnt[1].length)
              fam.push({ name: (nmf ? it[nmf] : `${k}[${i}]`) + "·" + kk, y: vv });
          }
        }
        if (fam.length) break; // 只展开第一个可展开的 dict_list（不硬猜多族）
      }
      if (fam.length)
        out.push({ title: t("tools.curvefam_title_tpl", { x: xKey }), xKey, x: xEnt[1], series: fam.slice(0, _TOOL_SERIES_CAP) });
    }
  }
  // ② 嵌套值对象 {x:[...], y:[...]} 形态：递归一层，标题带父键名
  if (out.length < _TOOL_CHART_CAP) {
    for (const [k, v] of entries) {
      if (!v || typeof v !== "object" || Array.isArray(v)) continue;
      for (const sub of toolDetectCurves(v)) {
        sub.title = `${k}：${sub.title}`;
        out.push(sub);
        if (out.length >= _TOOL_CHART_CAP) return out;
      }
    }
  }
  return out;
}

/* 纯函数（node 行为钉可测）：矩阵热图探测。列表的等长列表——
   - 复数矩阵（格=[re,im] 对）：须方阵（耦合矩阵 (N+2)²/gstc 2×2 家族；
     非方阵的 [re,im] 对列表更像零点/极点轨迹，不硬猜）→ 取模渲染；
   - 普通数值矩阵：列 ≥3（列 <3 更像点对列表）。
   返回 {key, rows, cols, complex, values(取模后), raw?} 或 null。 */
export function toolDetectMatrix(result) {
  if (!result || typeof result !== "object" || Array.isArray(result)) return null;
  for (const [key, rows] of Object.entries(result)) {
    if (!Array.isArray(rows) || rows.length < 2) continue;
    if (!rows.every((r) => Array.isArray(r) && r.length >= 2)) continue;
    const cols = rows[0].length;
    if (!rows.every((r) => r.length === cols)) continue;
    if (rows.length * cols > 4096) continue; // 防病态大矩阵卡渲染
    const flat = rows.flat();
    if (flat.every((c) => typeof c === "number" && Number.isFinite(c))) {
      if (cols < 3) continue;
      return { key, rows: rows.length, cols, complex: false, values: rows.map((r) => r.slice()) };
    }
    if (flat.every((c) => Array.isArray(c) && c.length === 2 &&
        c.every((x) => typeof x === "number" && Number.isFinite(x)))) {
      if (rows.length !== cols) continue; // 复数只认方阵（零点/极点列表不硬猜）
      return {
        key, rows: rows.length, cols, complex: true,
        values: rows.map((r) => r.map(([re, im]) => Math.hypot(re, im))),
        raw: rows,
      };
    }
  }
  return null;
}

/* 纯函数（node 行为钉可测）：扫参响应指标提取——被扫参数名以外的第一个
   标量数值键（同名回显按名排除；数组/布尔/NaN 不算标量指标）。
   探测不到返回 null（调用方不出曲线只出表格）。 */
export function toolPickSweepMetric(result, sweptKey) {
  for (const [k, v] of Object.entries(result || {})) {
    if (typeof v !== "number" || !Number.isFinite(v)) continue;
    if (k === sweptKey) continue;
    return { key: k, value: v };
  }
  return null;
}

/* 纯函数（node 行为钉可测）：公式面板特征探测——description 全文含 "="
   且含 "："/":" 才展开 details（注册表惯例 "名：用途：公式=闭式（出处）"）；
   无特征不显示。 */
export function toolDescHasFormula(desc) {
  const s = String(desc || "");
  return s.indexOf("=") >= 0 && /[：:]/.test(s);
}

/* 纯函数（node 行为钉可测）：结果表单元格文本——数组诚实截断（前 12 项 +
   总数）、矩阵给 [N×M 矩阵] 标签（全量见图/CSV 导出）、对象 JSON 串。
   不臆造数值，只做展示级折叠。 */
export function toolResultCellText(val) {
  if (val == null) return String(val);
  if (Array.isArray(val)) {
    if (val.length && val.every((r) => Array.isArray(r))) {
      const cols = val[0].length;
      return val.every((r) => r.length === cols)
        ? t("tools.cell_matrix_tpl", { r: val.length, c: cols })
        : t("tools.cell_nested_tpl", { n: val.length });
    }
    if (val.length > 12)
      return val.slice(0, 12).join(", ") + t("tools.cell_truncated_tpl", { n: val.length });
    return val.join(", ");
  }
  if (typeof val === "object") return JSON.stringify(val);
  return String(val);
}

/* 结果区折线 option（echartsInitCached 消费）：value x 轴 + [x,y] 点对；
   freq/tau 全正 → log x；全系列名命中 ber/adev 且全正 → log y
   （ber_log10 为负值，混系列时不给 log 轴——负值在 log 轴不渲染）。 */
function _toolLineOption(spec) {
  const light = bodyIsLight();
  const fg = themePick(light, THEME_COLORS.fg);
  const axis = {
    axisLine: { lineStyle: { color: themePick(light, THEME_COLORS.toolAxisLine) } },
    axisLabel: { color: themePick(light, THEME_COLORS.toolAxisLabel) },
    splitLine: { lineStyle: { color: themePick(light, THEME_COLORS.toolSplitLine) } },
  };
  const xlog = _TOOL_XLOG_RE.test(spec.xKey) && spec.x.every((v) => v > 0);
  const ylog = spec.series.every((s) => _TOOL_YLOG_RE.test(s.name)) &&
    spec.series.every((s) => s.y.every((v) => v > 0));
  return {
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: fg }, type: "scroll" },
    grid: { left: 56, right: 20, top: 34, bottom: 60 },
    xAxis: Object.assign(
      { type: xlog ? "log" : "value", scale: !xlog, name: spec.xKey,
        nameLocation: "middle", nameGap: 30, nameTextStyle: { color: fg } }, axis),
    yAxis: Object.assign(
      { type: ylog ? "log" : "value", scale: true, nameTextStyle: { color: fg } }, axis),
    dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 6 }],
    series: spec.series.map((s) => ({
      name: s.name, type: "line", showSymbol: spec.x.length <= 40,
      data: spec.x.map((xv, i) => [xv, s.y[i]]),
    })),
  };
}

/* 结果区热图 option（同 drawPattern3d 家族先例；复数矩阵取模，tooltip
   带原文 re/im——数据诚实）。 */
function _toolHeatmapOption(m) {
  const light = bodyIsLight();
  const fg = themePick(light, THEME_COLORS.fg);
  const cols = Array.from({ length: m.cols }, (_, i) => i);
  const rws = Array.from({ length: m.rows }, (_, i) => i);
  const data = [];
  for (let r = 0; r < m.rows; r++)
    for (let c = 0; c < m.cols; c++)
      data.push(m.complex
        ? [c, r, m.values[r][c], m.raw[r][c][0], m.raw[r][c][1]]
        : [c, r, m.values[r][c]]);
  const vals = data.map((d) => d[2]);
  const fmt = (v) => (+v).toPrecision(4);
  return {
    backgroundColor: "transparent",
    tooltip: { formatter: (q) => m.complex
      ? `${m.key}[${q.value[1]}][${q.value[0]}] = ${m.raw[q.value[1]][q.value[0]][0]} + ${m.raw[q.value[1]][q.value[0]][1]}j（|·|=${fmt(q.value[2])}）`
      : `${m.key}[${q.value[1]}][${q.value[0]}] = ${fmt(q.value[2])}` },
    grid: { left: 52, right: 70, top: 10, bottom: 34 },
    xAxis: { type: "category", data: cols, name: t("tools.col"), nameTextStyle: { color: fg }, axisLabel: { color: fg } },
    yAxis: { type: "category", data: rws, name: t("tools.row"), nameTextStyle: { color: fg }, axisLabel: { color: fg } },
    visualMap: {
      type: "continuous", min: Math.min(...vals), max: Math.max(...vals),
      right: 4, top: "middle", calculable: true, textStyle: { color: fg },
      inRange: { color: HEAT_BAND },
    },
    series: [{ type: "heatmap", data, animation: false, progressive: 2000 }],
  };
}

/* 结果图表实例自持句柄：#tool-result 每次 run 都 innerHTML 换血（缓存键随
   元素走，echartsInitCached 管不到旧元素）——渲染前统一释放上一轮实例
   （与 _isoRenderers 自愈同思路；不动 disposeChartsIn 既有装配点计数）。 */
let _toolResultCharts = [];

function resultChart(host, result) {
  for (const c of _toolResultCharts) if (c && !c.isDisposed()) c.dispose();
  _toolResultCharts = [];
  // 曲线优先：有曲线就不画矩阵（coupling_matrix_response 的 nfreq×2 复数
  // 表与本图重复；矩阵热图家族键均无 x-y 曲线，互斥不丢覆盖）
  const curves = toolDetectCurves(result);
  const mat = curves.length ? null : toolDetectMatrix(result);
  let n = 0;
  const draw = (title, option) => {
    const head = document.createElement("div");
    head.className = "muted";
    head.style.cssText = "margin:var(--space-2) 0 2px;font-size:12px";
    head.textContent = title;
    const el = document.createElement("div");
    el.style.height = "280px";
    host.appendChild(head);
    host.appendChild(el);
    const chart = echartsInitCached(el); // P0-5 同源守卫（唯一 init 入口）
    chart.setOption(option, true); // notMerge：复用路径整体替换
    bindChartResize(el); // 架构批 A3-A：resize 去重（WeakSet 单源）
    _toolResultCharts.push(chart);
    n++;
  };
  for (const spec of curves.slice(0, _TOOL_CHART_CAP)) {
    try {
      draw(spec.title, _toolLineOption(spec));
    } catch (e) {
      host.insertAdjacentHTML("beforeend",
        `<div class="muted">chart error: ${esc(e.message)}</div>`);
    }
  }
  if (mat) {
    const label = mat.complex
      ? t("tools.heat_complex_tpl", { key: mat.key, rows: mat.rows, cols: mat.cols })
      : t("tools.heat_tpl", { key: mat.key, rows: mat.rows, cols: mat.cols });
    try {
      draw(label, _toolHeatmapOption(mat));
    } catch (e) {
      host.insertAdjacentHTML("beforeend",
        `<div class="muted">heatmap error: ${esc(e.message)}</div>`);
    }
  }
  return n; // 0=无可视化形态（调用方保持纯 JSON 键值表，数据诚实）
}

export async function pageTools() {
  const v = T.$("view-tools");
  if (!v.innerHTML)
    v.innerHTML = help(`
      <li>${t("tools.help_1_lead")}<span id='tool-help-groups'>${t("tools.help_groups_loading")}</span>${t("tools.help_1_tail")}</li>
      <li>${t("tools.help_2")}</li>
      <li>${t("tools.help_3_lead")}<code>${t("tools.help_3_code")}</code>${t("tools.help_3_tail")}</li>`) +
    `<h2 class='page' data-i18n='tools.title'>${t("tools.title")}</h2>
     <div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>
       <div class='panel' style='flex:1;min-width:380px'>
         <div class='toolbar'><b data-i18n='tools.search_label'>${t("tools.search_label")}</b>
           <input id='tool-search' type='search' placeholder='${t("tools.search_placeholder")}' style='flex:1;min-width:140px' aria-label='${t("tools.search_aria")}' data-i18n-ph='tools.search_placeholder' data-i18n-aria='tools.search_aria'></div>
         <div class='toolbar'><b data-i18n='tools.calculators_label'>${t("tools.calculators_label")}</b>
           <select id='tool-name' style='flex:1' aria-label='${t("tools.select_aria")}'></select>
           <span id='tool-count' class='muted'></span></div>
         <div id='tool-desc' class='muted' style='margin:var(--space-2) 0;padding:var(--space-2);border:1px solid var(--border);border-radius:var(--radius-xs)'></div>
         <div id='tool-params'></div>
         <div id='tool-sweep' style='margin:var(--space-2) 0'></div>
         <div class='toolbar' style='margin-top:10px'>
           <button id='tool-run' class='primary'>${t("tools.run")}</button>
           <span id='tool-msg' class='muted'></span></div>
         <div id='tool-sweep-out' style='display:none'>
           <div id='tool-sweep-note' class='muted' style='padding:var(--space-1) 0'></div>
           <div id='tool-sweep-chart'></div>
           <div id='tool-sweep-table' style='max-height:260px;overflow:auto'></div>
         </div>
       </div>
       <div class='panel' style='flex:1;min-width:320px'><b class='title' data-i18n='tools.result_title'>${t("tools.result_title")}</b>
         <div id='tool-result' class='muted'>${t("tools.result_hint")}</div></div>
     </div>`;
  applyI18nRoot(v); // 壳静态标签首扫（语言档切到非 zh 时接管字面；W1-S2）
  _ensureToolsStyle();
  const d = await apiFetch("/api/calculators", { signal: viewSignal("tools") });
  if (d.aborted) return; // UI-R12：切页取消——用户已离开，不写隐藏区
  const cals = d.calculators || [];
  _toolsUI.cals = cals;
  const sel = T.$("tool-name");
  _toolsUI.sel = sel;
  const search = T.$("tool-search");
  // 帮助文案单源化（R5 §⑥：组清单由 API 数据自动生成，杜绝再犯陈旧；
  // 组名显示经 grpDisp——协议标识符保持中文单源）
  const groups = groupCalcList(cals);
  const gh = T.$("tool-help-groups");
  if (gh) gh.textContent = cals.length
    ? t("tools.help_groups_tpl", {
        n: cals.length, m: groups.length,
        list: groups.map((g) => grpDisp(g.group)).join("／"),
      })
    : t("tools.help_groups_unavailable");
  const renderParams = () => {
    const cal = cals.find((c) => c.name === sel.value) || { params: [] };
    // 双语说明面板（项 5）：中文名 + 用途（description 透传）+ 组徽章 + 实验态 + 英文 key
    const zh = calcZhName(cal);
    const purpose = String(cal.description || "").replace(/^[^：:]*[：:]\s*/, "")
      || (CALC_KEYS[cal.name] ? t(CALC_KEYS[cal.name][1]) : "");
    // A3-A 公式面板：description 全文含 "="、"：" 特征才出 details（等宽 pre，
    // 公式/出处原文可读可复制）；无特征不显示（不硬凑）。
    const descFull = String(cal.description || "");
    T.$("tool-desc").innerHTML =
      `<b style='color:var(--fg)'>${esc(zh)}</b> <code class='muted'>${esc(cal.name || "")}</code>` +
      (cal.name ? " " + T.badge(grpDisp(calcGroup(cal)), "muted") : "") +
      (cal.experimental ? " " + T.badge(t("tools.badge_experimental"), "warn") : "") +
      (purpose ? `<div style='margin-top:var(--space-1)'>${esc(purpose)}</div>` : "") +
      (toolDescHasFormula(descFull)
        ? `<details class='tool-formula'><summary>${t("tools.formula_summary")}</summary><pre>${esc(descFull)}</pre></details>`
        : "");
    const tp = T.$("tool-params");
    tp.innerHTML = cal.params
      .map((p) => {
        const { unit, text } = parseParamDesc(p.desc);
        return `<label class='muted' style='display:block;margin:var(--space-2) 0 2px'><b style='color:var(--fg)'>${esc(p.name)}</b>${p.required ? " <span style='color:var(--warn)'>*</span>" : ""}` +
          (unit ? ` <span class='badge muted'>${esc(unit)}</span>` : "") +
          ` <small>${esc(text)}</small>
        <input id='tool-p-${escAttr(p.name)}' style='width:100%' placeholder='${escAttr((p.required ? t("tools.ph_required") : t("tools.ph_optional")) + (unit ? "（" + unit + "）" : ""))}'></label>`;
      })
      .join("");
    // 微交互：参数表淡入（移除→强制重排→再加回，重复渲染可重触发；
    // prefers-reduced-motion 下由注入样式关闭）
    tp.classList.remove("tool-fade");
    void tp.offsetWidth;
    tp.classList.add("tool-fade");
    renderSweep(cal);
  };
  /* ── A3-A 扫参面板（R5 §⑤）：开关→选数值参数+起止点数→逐点串行调
     /api/calculators/run→抽响应指标画曲线；失败点如实跳过标记。
     点数上限 101（防滥用）。#tool-sweep-controls 随 renderParams 重建，
     #tool-sweep-out 常驻（图表容器不换血→plotCardCached 实例可复用）。 */
  const renderSweep = (cal) => {
    const sweepBox = T.$("tool-sweep");
    const prev = T.$("tool-sweep-on");
    const prevOn = !!(prev && prev.checked);
    const nums = (cal.params || [])
      .filter((p) => /^(float|int)/i.test(String(p.desc || "").trim()));
    sweepBox.innerHTML =
      `<label style='display:inline-flex;gap:6px;align-items:center;cursor:pointer'>` +
      `<input id='tool-sweep-on' type='checkbox'${prevOn ? " checked" : ""}` +
      `${nums.length ? "" : " disabled"}>` +
      `<b style='color:var(--fg)'>${t("tools.sweep_label")}</b>` +
      `<span class='muted'>${t("tools.sweep_note")}</span></label>` +
      (prevOn ? (nums.length
        ? `<div id='tool-sweep-controls' class='toolbar' style='flex-wrap:wrap;gap:var(--space-2);margin-top:6px'>` +
          `<select id='tool-sweep-param' aria-label='${t("tools.sweep_select_aria")}' style='max-width:200px'>` +
          nums.map((p) => `<option value="${escAttr(p.name)}">${esc(p.name)}</option>`).join("") +
          `</select>` +
          `<label class='muted'>${t("tools.sweep_start")}<input id='tool-sweep-start' type='number' style='width:90px'></label>` +
          `<label class='muted'>${t("tools.sweep_stop")}<input id='tool-sweep-stop' type='number' style='width:90px'></label>` +
          `<label class='muted'>${t("tools.sweep_points")}<input id='tool-sweep-points' type='number' value='21' min='2' max='101' style='width:70px'></label>` +
          `<button id='tool-sweep-go' class='minor'>${t("tools.sweep_go")}</button>` +
          `<span id='tool-sweep-msg' class='muted'></span></div>`
        : `<div class='muted' style='margin-top:var(--space-1)'>${t("tools.sweep_unavailable")}</div>`) : "");
    T.$("tool-sweep-out").style.display = "none"; // 换计算器：上一轮扫参产物收起（容器保留供复用）
    if (prevOn && nums.length) T.$("tool-sweep-go").onclick = () => runSweep(cal);
  };
  const runSweep = async (cal) => {
    const msg = T.$("tool-sweep-msg");
    const pName = T.$("tool-sweep-param") ? T.$("tool-sweep-param").value : "";
    if (!pName || !T.$("tool-sweep-start") || !T.$("tool-sweep-stop") ||
        !T.$("tool-sweep-points")) {
      msg.textContent = t("tools.sweep_not_ready");
      return;
    }
    const start = Number(T.$("tool-sweep-start").value);
    const stop = Number(T.$("tool-sweep-stop").value);
    const nPts = Number(T.$("tool-sweep-points").value);
    if (!Number.isFinite(start) || !Number.isFinite(stop)) {
      msg.textContent = t("tools.sweep_need_num");
      return;
    }
    if (!Number.isInteger(nPts) || nPts < 2 || nPts > 101) {
      msg.textContent = t("tools.sweep_points_range");
      return;
    }
    const go = T.$("tool-sweep-go");
    go.disabled = true;
    const goLabel = go.textContent;
    try {
      const rows = [];
      for (let i = 0; i < nPts; i++) {
        const xv = start + (stop - start) * i / (nPts - 1);
        msg.textContent = t("tools.sweep_progress_tpl", { i: i + 1, n: nPts, p: pName, x: xv });
        const params = collectParams(cal);
        params[pName] = xv;
        const r = await apiFetch("/api/calculators/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: sel.value, params }),
          timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：逐点扫描累计分钟级
        });
        if (r.ok) {
          const m = toolPickSweepMetric(r.result, pName);
          rows.push({ x: xv, y: m ? m.value : null, key: m ? m.key : null, error: null });
        } else {
          rows.push({ x: xv, y: null, key: null, error: r.error || t("tools.unknown_error") });
        }
      }
      renderSweepResult(pName, rows);
    } finally {
      go.disabled = false;
      go.textContent = goLabel;
      msg.textContent = "";
    }
  };
  const renderSweepResult = (pName, rows) => {
    const out = T.$("tool-sweep-out");
    const note = T.$("tool-sweep-note");
    const tableBox = T.$("tool-sweep-table");
    const ok = rows.filter((r) => r.y != null);
    const mkey = ok.length ? ok[0].key : null;
    const seriesRows = mkey != null ? ok.filter((r) => r.key === mkey) : [];
    // 失败点/无指标点如实逐行标记（不静默丢弃）
    // A7-A ui-kit 试点：表壳单源（kitTable；动态首列名由 kit 内 esc——与原
    // esc(pName) 同串）；rows 恒非空（点数 ≥2），empty:"" 保持空 tbody 等价
    tableBox.innerHTML = kitTable({
      columns: [pName, t("tools.th_response"), t("tools.th_status")], rows, empty: "",
      rowHtml: (r) =>
        `<tr><td class='muted'>${esc(r.x)}</td><td>${r.y == null ? "-" : "<b>" + esc(r.y) + "</b>"}</td>` +
        `<td>${r.error
          ? `<span style='color:var(--err)'>${t("tools.skipped_prefix")}${esc(r.error)}</span>`
          : (r.y == null ? `<span class='muted'>${t("tools.no_metric")}</span>` : "OK")}</td></tr>`,
    });
    out.style.display = "";
    if (seriesRows.length >= 2) {
      note.textContent = "";
      plotCardCached(T.$("tool-sweep-chart"), {
        series: [{ name: `${pName} → ${mkey}`, x: seriesRows.map((r) => r.x), y: seriesRows.map((r) => r.y) }],
        xlabel: pName, ylabel: mkey, height: "280px", zoom: false,
        exportName: "tool-sweep-" + sel.value,
      });
    } else {
      // 响应指标探测不到（或有效点 <2）——不出曲线只出表格（如实降级）
      note.textContent = t("tools.sweep_no_curve");
    }
  };
  _toolsUI.renderParams = renderParams;
  /* 参数收集单源（单点计算与扫参共用）：非空输入读出，数值形态转 number
     （与既有口径逐字节一致——raw 可解析即 number，否则原样字符串）。 */
  const collectParams = (cal) => {
    const params = {};
    for (const p of cal.params) {
      const el = T.$("tool-p-" + p.name);
      if (!el || el.value.trim() === "") continue;
      const raw = el.value.trim();
      const num = Number(raw);
      params[p.name] = raw !== "" && !Number.isNaN(num) ? num : raw;
    }
    return params;
  };
  /* 分组 optgroup 重绘：搜索词过滤 → 按组装配；选中项被滤掉时回落首个可见项 */
  const rebuildOptions = () => {
    const vis = cals.filter((c) => toolFilterMatch(c, search.value));
    sel.innerHTML = groupCalcList(vis)
      .map((g) => `<optgroup label="${escAttr(grpDisp(g.group))}（${g.items.length}）">` +
        g.items.map((c) =>
          `<option value="${escAttr(c.name)}">${esc(c.name)}（${esc(calcZhName(c))}）${c.experimental ? t("tools.opt_experimental") : ""}</option>`)
          .join("") + `</optgroup>`)
      .join("");
    T.$("tool-count").textContent = `${vis.length}/${cals.length}`;
    if (vis.length && !vis.some((c) => c.name === sel.value))
      sel.value = vis[0].name;
    renderParams();
  };
  /* 选择器变化 → hash 同步（replaceState 不产生历史条目、不触 hashchange） */
  const syncToolHash = () => {
    if (!sel.value) return;
    const want = "#/tools/" + encodeURIComponent(sel.value);
    if (location.hash !== want) history.replaceState(null, "", want);
  };
  sel.onchange = () => { renderParams(); syncToolHash(); };
  search.oninput = rebuildOptions;
  rebuildOptions(); // 列表头兜底初选
  // 深链消费（优先级高于列表头；键不存在回落列表头）：
  // 待选 key（toolsSelectKey 编程入口）优先，location.hash 自查兜底。
  const dk = _toolsPendingKey || toolsDeepLinkKey(location.hash);
  _toolsPendingKey = null;
  if (dk && dk !== sel.value && cals.some((c) => c.name === dk)) {
    sel.value = dk;
    renderParams();
  }
  syncToolHash();
  const runBtn = T.$("tool-run");
  runBtn.onclick = async () => {
    const cal = cals.find((c) => c.name === sel.value) || { params: [] };
    const params = collectParams(cal);
    // 微交互：loading 态（disabled + 文案）；finally 恢复——请求异常不得卡死按钮
    runBtn.disabled = true;
    const runLabel = runBtn.textContent;
    runBtn.textContent = t("tools.computing");
    T.$("tool-msg").textContent = t("tools.computing");
    try {
      const r = await apiFetch("/api/calculators/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: sel.value, params }),
        timeoutMs: 0, // 长跑豁免（P9-11 缺省超时）：计算器真算时长不定
      });
      const box = T.$("tool-result");
      if (!r.ok) {
        T.$("tool-msg").textContent = "";
        // W14-S2 错误呈现归一（R2 Top10 #4）：内联 ✗ span → kitErrorPanel 单源
        //（errorText 信封回退链；计算失败修复参数后重按「计算」，无重试钮）。
        box.innerHTML = kitErrorPanel(errorText(r));
        return;
      }
      T.$("tool-msg").textContent = t("tools.done");
      // A3-A 结果可视化：数组/曲线形态自动画图（识别不了的形态如实降级），
      // JSON 键值表并列保留（数据诚实；长数组展示级折叠，不臆造数值）
      box.innerHTML = "";
      resultChart(box, r.result);
      box.insertAdjacentHTML("beforeend", "<table><tbody>" + Object.entries(r.result)
        .map(([k, val]) =>
          `<tr><td class='muted'>${esc(k)}</td><td><b>${esc(toolResultCellText(val))}</b></td></tr>`)
        .join("") + "</tbody></table>");
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = runLabel;
    }
  };
}

/* ═══ R-1（架构批 W4-S17）：PageContext 增量钩子 toolsCtx ═════════════
   refresh=计算器注册表目录重拉（pageTools 幂等——壳判 innerHTML 已在即跳过；
   重拉后选项表重建=与重进同语义，深链/hash 待选键优先恢复）。无轮询面，
   leave 不需要。 */
export const toolsCtx = {
  refresh: () => pageTools(),
};
