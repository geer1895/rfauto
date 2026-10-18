/* rfauto 微波工具箱页（aurora_d UI-R2 自 pages.js 拆出，逐字节搬移）：
   计算器分组/搜索/深链（A2-B）+ 结果可视化/扫参/公式面板（A3-A）。
   数值只在确定性内核（规则 7）：本模块零物理数字产生。 */

import { HEAT_BAND, THEME_COLORS, bodyIsLight, themePick } from "../theme.js";
import { _isoRenderers, bindChartResize, echartsInitCached, plotCardCached } from "./charts.js";
import { T, getActiveView } from "./context.js";
import { esc, escAttr, help } from "./dom.js";
import { kitTable } from "./kit.js";
import { showPage } from "./router.js";

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

/* ── aurora72 A2-B：工具箱分组+搜索选择器与 #/tools/<key> 深链（R5 审计 §②§⑤§⑥）──
   契约：/api/calculators 每键带 group 字段（A2-A 席并行落地）——本席只消费
   c.group；字段缺席时回退"实验态→键名前缀粗映射→其他"，页面不炸。回退表刻意
   粗粒度（键名前缀，不复刻 133 键全表）——group 字段落地后回退仅剩兜底义。 */
const TOOL_GROUP_FALLBACK = [
  ["EMC·安规·放电", /^(conducted_|radiated_|esd_|exposure_|shielding_|corona_|multipactor_|ecss_)/],
  ["热·功率·可靠性", /^(thermal_|ipc2152_|microstrip_loss_heat|resonator_thermal_|electromigration_|parallel_plate_|microwave_process_|multimode_cavity_|single_mode_|form_beta_)/],
  ["测量与校准", /^(power_cal_|trl_|tnvna_|allan_)/],
  ["超材料·超表面", /^(homog_|retrieve_|srr_|wire_media_|crlh_|gstc_)/],
  ["量子读出", /^qubit_/],
  ["调制与数字链路", /^(modulation_|required_ebn0|coded_ber_|cdr_)/],
  ["天线与阵列", /^(array\.|cma_)/],
  ["DOA 与波束形成", /^doa_/],
  ["MIMO 与 RIS", /^(mimo_|ris_)/],
  ["雷达", /^(radar_|albersheim_|ca_cfar_)/],
  ["链路与传播", /^(sat_|gt_ratio|rfid_|chipless_|hata_|two_ray_|knife_edge_|rain_|gaseous_|availability_|fade_)/],
  ["收发链路·频综", /^(cascade_budget|correlated_cascade_|blocking_|spur_|if_plan_|iq_|phase_noise_|pll_|doherty_)/],
  ["滤波器与耦合矩阵", /^(chebyshev_|coupling_matrix_|cm_|q_factor_|qe_|mask_|cat_|k_split)/],
  ["谐振器与腔体", /^(coaxial_cavity_|combline_|cavity_|patch_length)/],
  ["匹配·功分·衰减·耦合", /^(attenuator_|quarter_wave_|t_match_|klopfenstein_|vswr_|unequal_split_|bethe_|balanced_pair_)/],
  ["传输线正反解", /^(microstrip|cpw|cpwg|cps|stripline|suspended_stripline|slotline|siw)_/],
];
/* 组序（R5 §② 建议）：常用在前；实验/其他恒殿后；未知组名（服务端新增组）
   按 zh 序排在已知组之后、殿后组之前。 */
const TOOL_GROUP_ORDER = [
  "传输线正反解", "匹配·功分·衰减·耦合", "滤波器与耦合矩阵", "谐振器与腔体",
  "天线与阵列", "DOA 与波束形成", "MIMO 与 RIS", "雷达", "链路与传播",
  "收发链路·频综", "调制与数字链路", "EMC·安规·放电", "热·功率·可靠性",
  "测量与校准", "超材料·超表面", "量子读出",
];
const TOOL_GROUP_EXPERIMENTAL = "实验";
const TOOL_GROUP_OTHER = "其他";

/* 组归属单源（纯函数，node 行为钉可测）：API group 字段优先；缺字段/空值
   回退 实验态→前缀粗映射→"其他"。 */
export function calcGroup(c) {
  if (c && typeof c.group === "string" && c.group.trim()) return c.group.trim();
  if (c && c.experimental) return TOOL_GROUP_EXPERIMENTAL;
  const name = String((c && c.name) || "");
  for (const [g, re] of TOOL_GROUP_FALLBACK) if (re.test(name)) return g;
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
   aurora72 A4-C 起收编为全站唯一 hashchange 监听——旧 app.js 页级 _applyHash
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
   参数表淡入 + 尊重系统"减少动态效果"设置 + aurora72 A3-A 公式面板/扫参
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

/* ═══ aurora72 A3-A：工具箱结果可视化 + 扫参 + 公式面板（R5 审计 §③§④§⑤）═══
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
      out.push({ title: `曲线（x=${xKey}）`, xKey, x: xEnt[1], series: series.slice(0, _TOOL_SERIES_CAP) });
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
        out.push({ title: `曲线族（x=${xKey}）`, xKey, x: xEnt[1], series: fam.slice(0, _TOOL_SERIES_CAP) });
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
        ? `[${val.length}×${cols} 矩阵]` : `[嵌套数组 ${val.length} 行]`;
    }
    if (val.length > 12)
      return val.slice(0, 12).join(", ") + ` …（共 ${val.length} 项）`;
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
    xAxis: { type: "category", data: cols, name: "列", nameTextStyle: { color: fg }, axisLabel: { color: fg } },
    yAxis: { type: "category", data: rws, name: "行", nameTextStyle: { color: fg }, axisLabel: { color: fg } },
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
    bindChartResize(el); // aurora72 A3-A：resize 去重（WeakSet 单源）
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
    const label = mat.complex ? `${mat.key} 热图（复数取模 |·|，${mat.rows}×${mat.cols}）`
      : `${mat.key} 热图（${mat.rows}×${mat.cols}）`;
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
      <li>闭式微波计算器 <span id='tool-help-groups'>清单加载中…</span>——组清单由注册表实时生成，不手工维护。顶部搜索框支持键名／中文名／用途实时过滤；下拉按组浏览。</li>
      <li>与综合引擎同口径（skrf Hammerstad-Jensen / Balanis 闭式）；必填参数标 *，留空的可选参数不传。</li>
      <li>同一 service 也开放在 CLI（rfauto calc）与 MCP（run_calculator）——三壳一个内核；深链 <code>#/tools/&lt;键名&gt;</code> 可直达并分享某计算器。</li>`) +
    `<h2 class='page'>微波工具箱</h2>
     <div style='display:flex;gap:14px;align-items:flex-start;flex-wrap:wrap'>
       <div class='panel' style='flex:1;min-width:380px'>
         <div class='toolbar'><b>搜索</b>
           <input id='tool-search' type='search' placeholder='键名 / 中文名 / 用途' style='flex:1;min-width:140px' aria-label='搜索计算器（键名、中文名、用途）'></div>
         <div class='toolbar'><b>计算器</b>
           <select id='tool-name' style='flex:1' aria-label='选择计算器（按组）'></select>
           <span id='tool-count' class='muted'></span></div>
         <div id='tool-desc' class='muted' style='margin:var(--space-2) 0;padding:var(--space-2);border:1px solid var(--border);border-radius:var(--radius-xs)'></div>
         <div id='tool-params'></div>
         <div id='tool-sweep' style='margin:var(--space-2) 0'></div>
         <div class='toolbar' style='margin-top:10px'>
           <button id='tool-run' class='primary'>计算</button>
           <span id='tool-msg' class='muted'></span></div>
         <div id='tool-sweep-out' style='display:none'>
           <div id='tool-sweep-note' class='muted' style='padding:var(--space-1) 0'></div>
           <div id='tool-sweep-chart'></div>
           <div id='tool-sweep-table' style='max-height:260px;overflow:auto'></div>
         </div>
       </div>
       <div class='panel' style='flex:1;min-width:320px'><b class='title'>结果</b>
         <div id='tool-result' class='muted'>选择计算器，填参数后点「计算」</div></div>
     </div>`;
  _ensureToolsStyle();
  const d = await T.api("/api/calculators");
  const cals = d.calculators || [];
  _toolsUI.cals = cals;
  const sel = T.$("tool-name");
  _toolsUI.sel = sel;
  const search = T.$("tool-search");
  // 帮助文案单源化（R5 §⑥：组清单由 API 数据自动生成，杜绝再犯陈旧）
  const groups = groupCalcList(cals);
  const gh = T.$("tool-help-groups");
  if (gh) gh.textContent = cals.length
    ? `共 ${cals.length} 键 · ${groups.length} 组：${groups.map((g) => g.group).join("／")}`
    : "清单不可用（服务未就绪？刷新重试）";
  const renderParams = () => {
    const cal = cals.find((c) => c.name === sel.value) || { params: [] };
    // 双语说明面板（项 5）：中文名 + 用途（description 透传）+ 组徽章 + 实验态 + 英文 key
    const zh = calcZhName(cal);
    const purpose = String(cal.description || "").replace(/^[^：:]*[：:]\s*/, "")
      || (CALC_ZH[cal.name] || [])[1] || "";
    // A3-A 公式面板：description 全文含 "="、"：" 特征才出 details（等宽 pre，
    // 公式/出处原文可读可复制）；无特征不显示（不硬凑）。
    const descFull = String(cal.description || "");
    T.$("tool-desc").innerHTML =
      `<b style='color:var(--fg)'>${esc(zh)}</b> <code class='muted'>${esc(cal.name || "")}</code>` +
      (cal.name ? " " + T.badge(calcGroup(cal), "muted") : "") +
      (cal.experimental ? " " + T.badge("实验态（默认不放行）", "warn") : "") +
      (purpose ? `<div style='margin-top:var(--space-1)'>${esc(purpose)}</div>` : "") +
      (toolDescHasFormula(descFull)
        ? `<details class='tool-formula'><summary>公式与出处（description 全文）</summary><pre>${esc(descFull)}</pre></details>`
        : "");
    const tp = T.$("tool-params");
    tp.innerHTML = cal.params
      .map((p) => {
        const { unit, text } = parseParamDesc(p.desc);
        return `<label class='muted' style='display:block;margin:var(--space-2) 0 2px'><b style='color:var(--fg)'>${esc(p.name)}</b>${p.required ? " <span style='color:var(--warn)'>*</span>" : ""}` +
          (unit ? ` <span class='badge muted'>${esc(unit)}</span>` : "") +
          ` <small>${esc(text)}</small>
        <input id='tool-p-${escAttr(p.name)}' style='width:100%' placeholder='${escAttr((p.required ? "必填" : "可选，留空不传") + (unit ? "（" + unit + "）" : ""))}'></label>`;
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
      `<b style='color:var(--fg)'>扫参模式</b>` +
      `<span class='muted'>（逐点串行调 /api/calculators/run，点数 ≤101）</span></label>` +
      (prevOn ? (nums.length
        ? `<div id='tool-sweep-controls' class='toolbar' style='flex-wrap:wrap;gap:var(--space-2);margin-top:6px'>` +
          `<select id='tool-sweep-param' aria-label='选择扫参（数值参数）' style='max-width:200px'>` +
          nums.map((p) => `<option value="${escAttr(p.name)}">${esc(p.name)}</option>`).join("") +
          `</select>` +
          `<label class='muted'>起点 <input id='tool-sweep-start' type='number' style='width:90px'></label>` +
          `<label class='muted'>终点 <input id='tool-sweep-stop' type='number' style='width:90px'></label>` +
          `<label class='muted'>点数 <input id='tool-sweep-points' type='number' value='21' min='2' max='101' style='width:70px'></label>` +
          `<button id='tool-sweep-go' class='minor'>扫描</button>` +
          `<span id='tool-sweep-msg' class='muted'></span></div>`
        : `<div class='muted' style='margin-top:var(--space-1)'>该计算器没有 float/int 数值参数，扫参不可用</div>`) : "");
    T.$("tool-sweep-out").style.display = "none"; // 换计算器：上一轮扫参产物收起（容器保留供复用）
    if (prevOn && nums.length) T.$("tool-sweep-go").onclick = () => runSweep(cal);
  };
  const runSweep = async (cal) => {
    const msg = T.$("tool-sweep-msg");
    const pName = T.$("tool-sweep-param") ? T.$("tool-sweep-param").value : "";
    if (!pName || !T.$("tool-sweep-start") || !T.$("tool-sweep-stop") ||
        !T.$("tool-sweep-points")) {
      msg.textContent = "扫参控件未就绪（请重选计算器）";
      return;
    }
    const start = Number(T.$("tool-sweep-start").value);
    const stop = Number(T.$("tool-sweep-stop").value);
    const nPts = Number(T.$("tool-sweep-points").value);
    if (!Number.isFinite(start) || !Number.isFinite(stop)) {
      msg.textContent = "起点/终点须为数值";
      return;
    }
    if (!Number.isInteger(nPts) || nPts < 2 || nPts > 101) {
      msg.textContent = "点数须为 2–101 的整数（上限 101 防滥用）";
      return;
    }
    const go = T.$("tool-sweep-go");
    go.disabled = true;
    const goLabel = go.textContent;
    try {
      const rows = [];
      for (let i = 0; i < nPts; i++) {
        const xv = start + (stop - start) * i / (nPts - 1);
        msg.textContent = `扫描中 ${i + 1}/${nPts}（${pName}=${xv}）`;
        const params = collectParams(cal);
        params[pName] = xv;
        const r = await T.api("/api/calculators/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: sel.value, params }),
        });
        if (r.ok) {
          const m = toolPickSweepMetric(r.result, pName);
          rows.push({ x: xv, y: m ? m.value : null, key: m ? m.key : null, error: null });
        } else {
          rows.push({ x: xv, y: null, key: null, error: r.error || "未知错误" });
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
      columns: [pName, "响应", "状态"], rows, empty: "",
      rowHtml: (r) =>
        `<tr><td class='muted'>${esc(r.x)}</td><td>${r.y == null ? "-" : "<b>" + esc(r.y) + "</b>"}</td>` +
        `<td>${r.error
          ? `<span style='color:var(--err)'>跳过：${esc(r.error)}</span>`
          : (r.y == null ? "<span class='muted'>无标量响应指标</span>" : "OK")}</td></tr>`,
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
      note.textContent = "响应指标探测不到（或有效点 <2）——不出曲线只出表格";
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
      .map((g) => `<optgroup label="${escAttr(g.group)}（${g.items.length}）">` +
        g.items.map((c) =>
          `<option value="${escAttr(c.name)}">${esc(c.name)}（${esc(calcZhName(c))}）${c.experimental ? " [实验]" : ""}</option>`)
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
    runBtn.textContent = "计算中...";
    T.$("tool-msg").textContent = "计算中...";
    try {
      const r = await T.api("/api/calculators/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: sel.value, params }),
      });
      const box = T.$("tool-result");
      if (!r.ok) {
        T.$("tool-msg").textContent = "";
        box.innerHTML = `<span style='color:var(--err)'>✗ ${esc(r.error)}</span>`;
        return;
      }
      T.$("tool-msg").textContent = "完成";
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

/* ═══ R-1（aurora_e W4-S17）：PageContext 增量钩子 toolsCtx ═════════════
   refresh=计算器注册表目录重拉（pageTools 幂等——壳判 innerHTML 已在即跳过；
   重拉后选项表重建=与重进同语义，深链/hash 待选键优先恢复）。无轮询面，
   leave 不需要。 */
export const toolsCtx = {
  refresh: () => pageTools(),
};
