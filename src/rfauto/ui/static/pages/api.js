/* rfauto 工作台统一 API 请求层（aurora_d UI-R12 任务2，前端深化席）。
   收敛目标：pages/ 各视图分散的 fetch/T.api 调用共用单一请求管道——
   ① 统一错误信封：{ok:false, error, errors} 与 app.js 全局 api 的消费
     契约同形（视图两种判法 `!d.ok`+d.error / (d.errors||[]).join 兼容）；
   ② Bearer token 透传：setApiToken 设置后所有请求自动带 Authorization
     头（缺省未设置=零新增头——存量请求逐字节等价）；
   ③ AbortController 取消（全部 opt-in）：视图作用域 signal（viewSignal）
     + 切页收束（abortViewSignals，app.js activate 消费）+ 请求超时
     （timeoutMs）。
   ④ 缺省超时（aurora_g W1-S1，R1 审计 P9-11 v9 Top4——能力在档零消费
     的补全；端点挂起=视图永久 pending，worker 池被慢请求饿干时正常
     页面是第一批殃及者）：**未传 timeoutMs 的请求一律挂 30s 超时**
     （_DEFAULT_TIMEOUT_MS）；显式 `timeoutMs: 0`=豁免（长跑触发端点
     POST /api/run、/api/tune/start、/api/calculators/run、/api/uq/yield、
     /api/chat、/api/hfss/import、/api/sandbox/promote、
     /api/playground/explore、POST /api/profile——这些本就分钟级，
     调用点已逐点标注）；
     显式正数=覆盖缺省。超时错误信息回显超时值（`请求超时（Nms …）`），
     复用 aborted 形态零新呈现面（不 toast，与主动取消同链）。
     **契约变更登记**：本条之前"未传 opts 的调用与旧 T.api 行为逐字节
     等价（fetch init 原样缺席）"——缺省超时后无 opts 请求也带超时
     signal（唯一差异；其余快照路径 timeoutMs:0 仍 init 缺席）。
   层次：本模块零依赖 pages/ 其他模块（node 裸 import 可测——桩 fetch 即
   真跑）；app.js 的全局 api（T.api 载体）保形消费 apiRequestInit 单源
   （其兜错信封与 msg 呈现被 test_ui_nav_focus 源码钉逐字钉住，留 app.js
   本体不动）；迁移终态（aurora_f W4-S13，R1 §面4 P8-9 收口）：全部视图
   （dashboard/runs/detail/calibration/data 五页=aurora_d UI-R12；palette+
   agent/recipe/tune=aurora_f W3-S9；余量 15 文件=sparams/reports/fieldviz/
   tools/loopboard/optstack/playground/solvers/import/gallery/campaign/
   profile/queue/timeline 视图族+filebrowser 模态，37 点 T.api+1 点裸
   fetch=aurora_f W4-S13）均走本层，pages/ 面 T.api 计数 65→58→37→0
   （终态防回潮钉 test_ui_r12_deepening）。 */

/* ── token 传递（默认关闭：未设置不加任何头）───────────────────────── */
let _token = null;
export function setApiToken(token) {
  _token = token == null || token === "" ? null : String(token);
}
/* 测试/诊断面：token 是否在效（不回显值，避免凭据经日志泄漏）。 */
export function apiTokenSet() {
  return _token != null;
}

/* token 注入装配（W6-S2，R2 审计 §面5.4 / Top10 #5——通道建成后的首个
   消费点）：服务端 RFAUTO_UI_TOKEN 设定时 index 响应注入
   <meta name="rfauto-ui-token">（ui/server.py 同 env 源中继——浏览器进程
   读不到服务端 env）；本模块装配期读取一次 → setApiToken → 之后全部
   apiFetch/app.js api 请求自动附 Authorization 头（apiRequestInit 单源）。
   守卫：无 document（node 裸 import 行为钉）或 querySelector 缺席静默跳过
   （#105 best-effort：装配面故障不得阻断请求层本体）；meta 缺席（服务端
   未启用鉴权）=零行为变化。安全语义：单操作者部署语境（页面可达者即持
   令者），门面价值在非浏览器通道写端点被拒；逐用户登录态不在本批。 */
if (typeof document !== "undefined" &&
    typeof document.querySelector === "function") {
  try {
    const m = document.querySelector('meta[name="rfauto-ui-token"]');
    if (m && m.content) setApiToken(m.content);
  } catch { /* best-effort 静默 */ }
}

/* ── mock 通道（aurora_i W3.5-K3 UI 离线开发回路，opt-in 双闸）────────
   setApiMockBase(base) 设置后 apiFetch 仅对**相对 /api/ 路径**做前缀
   改写（相对 api 路径前缀替换为 base 同形；绝对 URL 与非 api 路径原样——SSE/
   静态资源不经此），配 scripts/ui_dev_loop.py 的 mock 数据服务或任意
   静态伺服跨源取数。超时/Bearer/错误信封/取消逻辑逐字节不变（只换
   URL）。装配期激活面（best-effort，#105 同款守卫）：URL 查询 ?mock=1
   （默认基址 /mock/）或 ?mock=<base> 显式；**会话级不落 localStorage**
   ——刷新即回真通道，防 mock 读数被误当真值消费（纪律见
   docs/how-to/ui-offline-dev.md）。缺省（无查询参数/未设置）零行为
   变化——存量请求逐字节等价。
   覆盖面说明：仅 apiFetch（视图 27 文件已全迁移）；app.js 全局 api
   （T.api 载体）不经本开关，直连面清单见 how-to 篇限制节。 */
let _mockBase = null;
export function setApiMockBase(base) {
  _mockBase = base == null || base === "" ? null : String(base);
}
/* 测试/诊断面：当前 mock 基址（null=真通道）。 */
export function apiMockBase() {
  return _mockBase;
}
if (typeof location !== "undefined" && typeof location.search === "string") {
  try {
    const mm = location.search.match(/[?&]mock=([^&]*)/);
    if (mm) {
      const v = decodeURIComponent(mm[1]);
      setApiMockBase(v === "" || v === "1" ? "/mock/" : v);
    }
  } catch { /* best-effort 静默 */ }
}

/* ── 失败呈现注入（app.js msg 单源；node/异常部署缺席时静默，#105）── */
let _notifier = null;
export function setApiNotifier(fn) {
  _notifier = typeof fn === "function" ? fn : null;
}

/* ── 统一错误卡呈现注入（UI 人性化批 R4，opt-in 双闸）──────────────────
   注入面与 _notifier 同构（kit.js 装配期注册缺省实现=showApiError，本模块
   保持零 pages/ 依赖纪律——注册的是函数引用非模块依赖）。消费面双闸：
   ①调用点显式 opts.apiError（真值=启用；对象形态则透传为呈现参数
   {title,hint,...}）②注册表非空。缺省（无 flag/无注册）零行为变化——
   存量调用逐字节等价（他席在改页不被波及）。触发面只限"服务端已应答的
   ok:false 信封"（JSON 解析成功路径）；网络层失败（catch 分支）已由
   _notifier toast 覆盖，此处不再叠加防双呈现；aborted（主动取消/超时）
   不触发——取消不是错误卡语义。呈现失败吞掉不阻返回（#105：呈现面
   不得成为请求主路径故障点），信封原样返回=调用方既有分支照常工作。 */
let _errorPresenter = null;
export function setApiErrorPresenter(fn) {
  _errorPresenter = typeof fn === "function" ? fn : null;
}

/* 失败文案（与 app.js api 兜底同串：两管道呈现语义一致）。 */
const _ERR_TEXT = "请求失败（网络或服务器异常）";

/* 缺省超时（P9-11，aurora_g W1-S1）：30s 量级覆盖全部只读/快端点；
   长跑触发端点由调用点显式 `timeoutMs: 0` 豁免（见头注④清单）。 */
const _DEFAULT_TIMEOUT_MS = 30000;

/* 超时文案（回显超时值——调用方可辨识是缺省 30s 还是显式值触发）。 */
function _timeoutErrText(ms) {
  return `请求超时（${ms}ms 无响应，已中止）`;
}

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
   视图以 `if (d.aborted) return;` 短路后续渲染；缺省超时（头注④）同入
   aborted 形态，error 文案回显超时值）。 */
export async function apiFetch(url, opts = null) {
  // mock 通道（W3.5-K3）：仅改写相对 /api/ 路径，其余（绝对 URL/静态
  // 资源/SSE）原样——改写发生在超时/token 装配之前，两者互不感知。
  // 基址若已以 /api 结尾则不重复拼接（?mock=http://host:port/api 直指
  // 真服务同形路径；/mock 基址则拼出 /mock/api/...）。
  if (_mockBase && typeof url === "string") {
    const mm = url.match(/^\/?(api\/.*)$/);
    if (mm) {
      const base = _mockBase.replace(/\/+$/, "");
      const rest = /\/api$/.test(base) ? mm[1].slice(4) : mm[1];
      url = base + "/" + rest;
    }
  }
  let init = opts || undefined;
  let cancelTimeout = () => {};
  let timedOutMs = 0; // >0=本请求因超时被中止（回显值；caller abort 不置位）
  try {
    const o = opts || {};
    const to = o.timeoutMs == null ? _DEFAULT_TIMEOUT_MS : o.timeoutMs;
    if (to > 0 && typeof AbortController === "function") {
      const tc = new AbortController();
      const t = setTimeout(() => { timedOutMs = to; tc.abort(); }, to);
      cancelTimeout = () => clearTimeout(t);
      init = { ...o, signal: composeSignals([o.signal, tc.signal]) };
    }
    const r = await fetch(url, apiRequestInit(init));
    const d = await r.json(); // await 留在 try 内：json 解析失败同样入 catch
    // 统一错误卡（R4，opt-in 双闸——见 setApiErrorPresenter 头注）：
    // 只对"服务端已应答的 ok:false 信封"触发；呈现失败静默、信封原样返回。
    if (d && typeof d === "object" && d.ok === false && !d.aborted &&
        o.apiError && _errorPresenter) {
      try {
        _errorPresenter(d, typeof o.apiError === "object" ? o.apiError : {});
      } catch { /* #105：呈现面故障不阻请求主路径 */ }
    }
    return d;
  } catch (e) {
    if (e && (e.name === "AbortError" || e.name === "TimeoutError")) {
      if (timedOutMs > 0) {
        const msg = _timeoutErrText(timedOutMs);
        return { ok: false, error: msg, errors: [msg], aborted: true };
      }
      return { ok: false, error: _ERR_TEXT, errors: [_ERR_TEXT], aborted: true };
    }
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
