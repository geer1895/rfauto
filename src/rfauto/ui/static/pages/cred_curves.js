/* rfauto 可信度对照曲线共享数据模块（aurora_i W3-S2，R3 设计 M3 前端半）。

   数据面 = GET /api/credibility/curves（W3-S1 服务席落地：
   service/credibility_curves_service.credibility_curves，路由装配在其
   席位；前端零文件读取——runs 挂载缺省关（R2-B-05），凡 runs/ 产物一律
   由服务层读）。查询参数 template 单参（R3 设计 N2 口径用
   template、服务层签名参数名 model——路由读哪个都命中，多余参数无害）。

   前端消费契约（=credibility_curves_service 实际信封，W3-S1 2026-10-19）：
     { ok:true, schema_version, model,
       engines:{ hfss|openems: { available, source, n_ports, n_points,
                                 freq_ghz[], curves:[{name,s_db[]}],
                                 omitted_filled[], mask_note, note } },
       pairing:{ state: "paired"|"single_engine"|"no_overlap", same_grid?,
                 match_rule?, n_matched?, overlap_ghz?, max_dev_db?,
                 worst?:{name,max_dev_db,at_ghz}, note? },
       verdict:{ available, source, states[], counts{agree,disagree,
                 unknown,total} } | 空形态,
       provenance:{ hfss?, openems?, verdict?, runs_root },
       notes:[...] }
   未注册模板=诚实空信封（ok:true、engines 空、available_templates）。
   曲线值已是 dB 域（服务层 20·log10(|S|+1e-12)，sparams_series 同式），
   前端不再做数值变换；偏差注记优先信封 pairing.worst（服务端同栅/最近
   邻 #287/#294 口径），缺席走客户端最近邻兜底。

   本模块纪律：纯数据零 DOM 零 t()（i18n 文案由消费视图烘焙——键集互证
   页前缀死键口径）；apiFetch 一层依赖（node 桩 fetch 可测）；渲染红线：
   无数据=整节隐藏（消费视图负责）、单引擎=单线+note、DISAGREE 如实
   徽章不凑绿（#122 家族）。 */

import { apiFetch } from "./api.js";
import { THEME_COLORS, themePick } from "../theme.js";

export const CRED_CURVES_ENDPOINT = "/api/credibility/curves";

/* 引擎着色（theme.js 单源色对——pages/ 引号 hex 字面量归零棘轮口径；
   hfss=仲裁基准橙 / openems=主力引擎蓝 / 其余引擎=中性灰单源；取档经
   themePick(light, pair) 由消费面按当前主题传入——与 view_fieldviz 的
   THEME_COLORS 消费先例同口径）。 */
export const CRED_ENGINE_COLOR_PAIRS = {
  hfss: THEME_COLORS.seriesOrange,
  openems: THEME_COLORS.seriesBlue,
  reference: THEME_COLORS.emptyCell,
  mmt: THEME_COLORS.emptyCell,
  unknown: THEME_COLORS.calibNullCost,
};

/* 引擎排序权重（hfss=仲裁基准在前，openems=主力引擎次之）。 */
function _engineRank(e) {
  return e === "hfss" ? 0 : e === "openems" ? 1
    : e === "reference" ? 2 : e === "mmt" ? 3 : 9;
}

/* 曲线条目引擎归一：engine/engine_id 显式标签优先；缺席按 file 名兜底
   （/hfss/i → hfss；/openems|fdtd/i → openems）；再缺席 unknown。 */
export function credEngineOf(c) {
  const e = String((c && (c.engine || c.engine_id)) || "").toLowerCase();
  if (e) return e;
  const f = String((c && c.file) || "");
  if (/hfss/i.test(f)) return "hfss";
  if (/openems|fdtd/i.test(f)) return "openems";
  return "unknown";
}

/* 信封→视图模型（纯函数）：engines.{hfss,openems} 可用引擎的 curves
   （name+s_db，共享该引擎 freq_ghz 轴）展平为 {engine,name,file,x,y}
   线族（频轴/曲线等长守卫，非数清洗）、engines 去重排序、hasPair=双
   引擎在盘（pairing.state=no_overlap 也算——两线都画，偏差注记走
   cred_dev_na 诚实行）、maxDev=信封 pairing.worst、verdict/notes/
   provenance 透传。 */
export function credNormalize(d) {
  const curves = [];
  const engines = [];
  const engs = d && d.engines && typeof d.engines === "object" &&
    !Array.isArray(d.engines) ? d.engines : {};
  for (const key of Object.keys(engs)) {
    const e = engs[key];
    if (!e || !e.available || !Array.isArray(e.freq_ghz) ||
        !e.freq_ghz.length) continue;
    const x = e.freq_ghz.map(Number);
    if (x.some((v) => !Number.isFinite(v))) continue;
    const ecl = credEngineOf({ engine: key, file: e.source });
    const cl = Array.isArray(e.curves) ? e.curves : [];
    for (const c of cl) {
      if (!c || !Array.isArray(c.s_db) || !c.s_db.length) continue;
      const y = c.s_db.map(Number);
      if (y.length !== x.length || y.some((v) => !Number.isFinite(v)))
        continue; // 频轴/曲线等长守卫：形态不合整条丢弃（不半拉出线）
      curves.push({
        engine: ecl,
        name: String(c.name || "S"),
        file: String(e.source || ""),
        x, y,
      });
    }
    if (cl.some((c) => c && Array.isArray(c.s_db) && c.s_db.length &&
        c.s_db.length === x.length))
      engines.push(ecl);
  }
  engines.sort((a, b) => _engineRank(a) - _engineRank(b));
  const prov = d && d.provenance && typeof d.provenance === "object"
    ? d.provenance : {};
  const sources = [prov.hfss, prov.openems, prov.verdict]
    .filter((s) => s != null && String(s).trim()).map(String);
  const notes = d && Array.isArray(d.notes) ? d.notes.map(String) : [];
  const verdict = d && d.verdict && d.verdict.available ? d.verdict : null;
  return {
    curves, engines, sources, notes, verdict,
    hasPair: engines.length >= 2,
    maxDev: _parseMaxDev(d),
  };
}

/* 信封 pairing.worst → 偏差注记（服务端 #287/#294 口径现成数字直用；
   state≠paired / worst 缺角= null——交客户端同口径兜底）。 */
function _parseMaxDev(d) {
  const p = d && d.pairing;
  if (!p || p.state !== "paired") return null;
  const w = p.worst;
  if (!w || !w.name || !Number.isFinite(+w.max_dev_db)) return null;
  return {
    name: String(w.name),
    dev: +w.max_dev_db,
    freq: Number.isFinite(+w.at_ghz) ? +w.at_ghz : null,
  };
}

/* 单对曲线最大偏差（最近邻频点对齐，#294 argmin|Δf| 口径；|Δf| 超容差
   的点跳过不入注记）。A 侧按确定性等步长抽稀到 ≤400 点再配对（万点级
   宽扫的 O(n²) 配对防劣化；抽稀只影响注记精度不影响图形本体）。 */
function _pairDev(ca, cb) {
  const span = Math.max(
    (ca.x[ca.x.length - 1] - ca.x[0]) || 0,
    (cb.x[cb.x.length - 1] - cb.x[0]) || 0);
  const tol = Math.max(1e-6, span * 0.01);
  const step = Math.max(1, Math.floor(ca.y.length / 400));
  let best = null;
  for (let i = 0; i < ca.y.length; i += step) {
    let bj = -1, bd = Infinity;
    for (let j = 0; j < cb.x.length; j++) {
      const df = Math.abs(cb.x[j] - ca.x[i]);
      if (df < bd) { bd = df; bj = j; }
    }
    if (bj < 0 || bd > tol) continue;
    const dev = Math.abs(ca.y[i] - cb.y[bj]);
    if (!best || dev > best.dev) best = { dev, freq: ca.x[i] };
  }
  return best;
}

/* 客户端兜底偏差注记：同名（S11/S21…）曲线按引擎对（hfss×openems 优先，
   缺一侧时 reference/mmt 兜底配对）逐对计算，取全局最大。无可配对返回
   null（消费视图显示诚实"频网不齐"行）。 */
export function credMaxDev(curves) {
  const byName = new Map();
  for (const c of curves || []) {
    if (!byName.has(c.name)) byName.set(c.name, {});
    const g = byName.get(c.name);
    (g[c.engine] = g[c.engine] || []).push(c);
  }
  const pick = (g) => g.hfss && g.openems
    ? [[g.hfss, g.openems]]
    : g.openems && (g.reference || g.mmt)
      ? [[g.openems, g.reference || g.mmt]]
      : [];
  let best = null;
  for (const [name, g] of byName) {
    for (const [as, bs] of pick(g))
      for (const ca of as) for (const cb of bs) {
        const r = _pairDev(ca, cb);
        if (r && (!best || r.dev > best.dev))
          best = { name, dev: r.dev, freq: r.freq };
      }
  }
  return best;
}

/* plotCard series 组装（{name,x,y,color}；labelOf(曲线)=引擎标签由消费
   视图 i18n 烘焙——本模块零 t()；light=当前主题档（消费面 bodyIsLight()
   现取），经 themePick 取单源色对档位）。输出可直接喂 T.plotCard/
   buildEChartOption（line 族，数据形态在 tests/unit/test_ui_cred_curves
   .py 钉）。消费口径（aurora_j W1-S1 异栅根治）：消费视图一律传
   xvalue:true——双引擎各自 freq_ghz 频网点数/间距可不同，值轴下每条
   迹线以自持 [x,y] 网出数（category 轴按索引共享 series[0].x 会把第二
   引擎拉伸错位）；同栅场景值轴同样无损。 */
export function credSeries(curves, labelOf, light) {
  return (curves || []).map((c) => ({
    name: labelOf(c),
    x: c.x,
    y: c.y,
    color: themePick(light,
      CRED_ENGINE_COLOR_PAIRS[c.engine] || CRED_ENGINE_COLOR_PAIRS.unknown),
  }));
}

/* 引擎图例短标签（专有名词，语言中立——角色/配色语义由消费视图的图例
   注记行 i18n 承担：HFSS=仲裁基准（橙）/openEMS=主力引擎（蓝））；
   unknown=原样引擎 id（API 数据，与曲线名 S11 同信任级——chart series
   label 豁免面）。 */
export function credEngineTag(e) {
  if (e === "hfss") return "HFSS";
  if (e === "openems") return "openEMS";
  if (e === "reference") return "REF";
  if (e === "mmt") return "mmt";
  return String(e || "?");
}

/* 一站式 series（同引擎同名多文件去重歧义：追加 file 段消歧）。 */
export function credSeriesLabeled(curves, light) {
  const counts = new Map();
  for (const c of curves || []) {
    const k = c.engine + "|" + c.name;
    counts.set(k, (counts.get(k) || 0) + 1);
  }
  return credSeries(curves, (c) =>
    credEngineTag(c.engine) + "·" + c.name +
    (counts.get(c.engine + "|" + c.name) > 1 && c.file ? "·" + c.file : ""),
  light);
}

/* ── 取数与缓存（画廊抽屉 + S 参数页对照模式共用单点）───────────────
   三级缓存语义：
   - 命中（data/empty）直接返回（同模板抽屉反复开关/S 参数重渲零重发）；
   - ok 信封按曲线有无落 data/empty（未注册模板=服务端诚实空信封→
     empty，不当故障渲染）；ok:false 信封=服务端明示无对照（逐模板
     负缓存）；
   - 非信封响应（{detail:...} 等，典型=端点未落地 404）→ 会话级
     _routeMissing 短路（后续抽屉零请求风暴；页面刷新自然复位）。
   aborted（切页取消/超时）不落缓存——重开抽屉自然重发。 */
const _cache = new Map(); // template → {status:"data",view}|{status:"empty"}
let _routeMissing = false;

export function credCacheSize() {
  return _cache.size;
}

export async function credFetch(template, signal) {
  const key = String(template || "");
  if (_routeMissing) return { status: "empty" };
  const hit = _cache.get(key);
  if (hit) return hit;
  // 查询参数：template 单参（服务端只声明此参；原设计期的服务层
  // 签名双兼容已随契约门收敛退役——aurora_i W3 合流项）。
  const d = await apiFetch(
    "/api/credibility/curves?template=" + encodeURIComponent(key),
    { signal });
  if (d && d.aborted) return { status: "empty", aborted: true };
  let entry;
  if (d && d.ok) {
    const view = credNormalize(d);
    entry = view.curves.length ? { status: "data", view } : { status: "empty" };
  } else if (d && d.ok === false) {
    entry = { status: "empty" };
  } else {
    _routeMissing = true;
    entry = { status: "empty" };
  }
  _cache.set(key, entry);
  return entry;
}
