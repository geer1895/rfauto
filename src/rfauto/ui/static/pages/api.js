/* rfauto 工作台统一 API 请求层（aurora_d UI-R12 任务2，前端深化席）。
   收敛目标：pages/ 各视图分散的 fetch/T.api 调用共用单一请求管道——
   ① 统一错误信封：{ok:false, error, errors} 与 app.js 全局 api 的消费
     契约同形（视图两种判法 `!d.ok`+d.error / (d.errors||[]).join 兼容）；
   ② Bearer token 透传：setApiToken 设置后所有请求自动带 Authorization
     头（缺省未设置=零新增头——存量请求逐字节等价）；
   ③ AbortController 取消（全部 opt-in）：视图作用域 signal（viewSignal）
     + 切页收束（abortViewSignals，app.js activate 消费）+ 请求超时
     （timeoutMs）。未传 opts 的调用与旧 T.api 行为逐字节等价。
   层次：本模块零依赖 pages/ 其他模块（node 裸 import 可测——桩 fetch 即
   真跑）；app.js 的全局 api（T.api 载体，70 处存量调用点）保形消费
   apiRequestInit 单源（其兜错信封与 msg 呈现被 test_ui_nav_focus 源码钉
   逐字钉住，留 app.js 本体不动）；渐进迁移视图直接 import apiFetch/
   viewSignal（本席先迁 dashboard/runs/detail/calibration/data 五高频页，
   其余 T.api 调用点后续席位按同一口径迁移）。 */

/* ── token 传递（默认关闭：未设置不加任何头）───────────────────────── */
let _token = null;
export function setApiToken(token) {
  _token = token == null || token === "" ? null : String(token);
}
/* 测试/诊断面：token 是否在效（不回显值，避免凭据经日志泄漏）。 */
export function apiTokenSet() {
  return _token != null;
}

/* ── 失败呈现注入（app.js msg 单源；node/异常部署缺席时静默，#105）── */
let _notifier = null;
export function setApiNotifier(fn) {
  _notifier = typeof fn === "function" ? fn : null;
}

/* 失败文案（与 app.js api 兜底同串：两管道呈现语义一致）。 */
const _ERR_TEXT = "请求失败（网络或服务器异常）";

/* AbortSignal 组合：AbortSignal.any 在场直接用；缺席引擎（旧 Safari 等，
   与 sse/polling 降级纪律同款）手工前向 abort。空集返回 undefined=
   fetch(url, {signal: undefined}) ≡ 不传 signal。 */
export function composeSignals(signals) {
  const live = (signals || []).filter(Boolean);
  if (live.length === 0) return undefined;
  if (live.length === 1) return live[0];
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.any === "function")
    return AbortSignal.any(live);
  const ac = new AbortController();
  for (const s of live) {
    if (s.aborted) { ac.abort(s.reason); break; }
    s.addEventListener("abort", () => ac.abort(s.reason), { once: true });
  }
  return ac.signal;
}

/* 请求 init 归一（app.js api 与 apiFetch 共用单源）：headers 合并 +
   Authorization 透传；signal 面由调用方组合后经 opts.signal 传入。
   快路径：无 opts 且无 token → 原样返回（fetch(url, undefined) 与旧
   全局 api 逐字节等价）。 */
export function apiRequestInit(opts) {
  if (!opts && !_token) return opts;
  const o = opts || {};
  const headers = { ...(o.headers || {}) };
  if (_token && headers.Authorization == null)
    headers.Authorization = "Bearer " + _token;
  return { ...o, headers };
}

/* 统一请求入口：成功=解析后的 JSON 信封；失败=同形错误信封（aborted
   形态多带 aborted:true 且不触发 toast——调用方主动取消不是网络故障，
   视图以 `if (d.aborted) return;` 短路后续渲染）。 */
export async function apiFetch(url, opts = null) {
  let init = opts || undefined;
  let cancelTimeout = () => {};
  try {
    const o = opts || {};
    if (o.timeoutMs != null && o.timeoutMs > 0 &&
        typeof AbortController === "function") {
      const tc = new AbortController();
      const t = setTimeout(() => tc.abort(), o.timeoutMs);
      cancelTimeout = () => clearTimeout(t);
      init = { ...o, signal: composeSignals([o.signal, tc.signal]) };
    }
    const r = await fetch(url, apiRequestInit(init));
    return await r.json(); // await 留在 try 内：json 解析失败同样入 catch
  } catch (e) {
    if (e && (e.name === "AbortError" || e.name === "TimeoutError"))
      return { ok: false, error: _ERR_TEXT, errors: [_ERR_TEXT], aborted: true };
    if (_notifier) try { _notifier(_ERR_TEXT, false); } catch { /* 静默 */ }
    return { ok: false, error: _ERR_TEXT, errors: [_ERR_TEXT] };
  } finally {
    cancelTimeout();
  }
}

/* ── 视图作用域取消（opt-in）────────────────────────────────────────
   迁移视图发请求时取 viewSignal(<页键>)；app.js activate 切页时调
   abortViewSignals() 收束全部在途——用户已离开的页其 fire-and-forget
   渲染不再写隐藏区（重进该页时 viewSignal 惰性建新 controller，请求
   自然重发）。未迁移视图（T.api 直调）零影响。 */
const _viewControllers = new Map();
export function viewSignal(view) {
  let ac = _viewControllers.get(view);
  if (!ac || ac.signal.aborted) {
    ac = new AbortController();
    _viewControllers.set(view, ac);
  }
  return ac.signal;
}
export function abortViewSignals() {
  for (const ac of _viewControllers.values())
    if (!ac.signal.aborted) ac.abort();
  _viewControllers.clear();
}
