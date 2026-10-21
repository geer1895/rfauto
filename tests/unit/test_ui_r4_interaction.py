"""UI 人性化批 R4（交互细节与公共组件席）回归钉。

用户反馈"很多按钮的操作问题"（点运行甩裸 JSON/按钮无 loading 禁用态/
错误呈现各页不一/空态没引导）的公共件收口三层钉：

1. 行为钉（node 真执行，缺 node skip）：
   - kitApiErrorHtml 统一错误卡（标题 badge/错误原文/建议行三段结构；
     errors[] join；无 errors 信封回退通用文案；错误文本 esc 单点转义）；
   - showApiError 无 document 守卫返回 null（kitConfirm 同款口径）；
   - kitBtnBusy 三态（busy=disabled+aria-busy+spinner 文案/restore 还原
     钮面/幂等/非元素静默）；缺省钮面=common.busy 词表值；
   - api.js apiError opt-in 双闸矩阵（缺省零行为/flag 布尔与对象两形态/
     呈现异常吞掉信封原样返回/未注册 no-op/aborted 不触发/kit.js 装配
     自动注册）；
   - i18n 新键双语齐全（append-only 增量键清单）。
2. 源码钉（免 node）：单源导出唯一/长操作按钮 busy 接线点/旧手写 disabled
   形态不回潮/空态三件式接线/危险操作确认接线/api.js 开关消费在位。
3. 跨席钉保护：✗ 计数、T.api 棘轮零、queue 豁免点不动（引用计数断言，
   细钉本体归各原测试文件）。

不依赖 runs/、不读网络、不启动服务器。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_KIT = (_STATIC / "pages" / "kit.js").read_text(encoding="utf-8")
_API = (_STATIC / "pages" / "api.js").read_text(encoding="utf-8")
_I18N = (_STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
_RUNS = (_STATIC / "pages" / "view_runs.js").read_text(encoding="utf-8")
_DATA = (_STATIC / "pages" / "view_data.js").read_text(encoding="utf-8")
_IMPORT = (_STATIC / "pages" / "view_import.js").read_text(encoding="utf-8")
_PROFILE = (_STATIC / "pages" / "view_profile.js").read_text(encoding="utf-8")
_SOLVERS = (_STATIC / "pages" / "view_solvers.js").read_text(encoding="utf-8")


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


def _kit_call(expr: str) -> str:
    return _run_node_js(
        f"const kit = await import('./pages/kit.js');\n"
        f"console.log(JSON.stringify({expr}));\n")


# ────────────────────── 1. 行为钉（node 真执行） ──────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
class TestKitApiErrorCardNode:
    def test_card_structure_with_errors_and_overrides(self):
        """三段结构：标题 badge + 错误原文（errors join）+ 建议行；覆盖传参。"""
        out = json.loads(_kit_call(
            "kit.kitApiErrorHtml({ ok: false, errors: ['E1', 'E2'] },"
            " { title: '导入失败: ', hint: '检查 .lock' })"))
        assert '<div class="err-panel" role="alert">' in out
        assert '<span class="badge err">导入失败: </span>' in out
        assert '<span class="muted">E1; E2</span>' in out
        assert "检查 .lock" in out

    def test_generic_fallback_when_no_errors(self):
        """无 errors 信封：标题/正文/建议全走 common.* 词表缺省档（zh）。"""
        out = json.loads(_kit_call("kit.kitApiErrorHtml({ ok: false }, {})"))
        assert "<span class=\"badge err\">操作失败</span>" in out
        assert "操作未成功（服务未就绪或请求异常），可稍后重试" in out
        assert "若持续失败，请查看服务端日志，或刷新页面重试" in out

    def test_hint_suppressible_and_error_text_escaped(self):
        """hint 传空串显式去建议行；错误原文（API 数据）esc 单点转义。"""
        out = json.loads(_kit_call(
            "kit.kitApiErrorHtml({ ok: false,"
            " errors: ['<img src=x onerror=alert(1)>'] }, { hint: '' })"))
        assert "<img" not in out and "&lt;img" in out
        assert 'flex-basis:100%' not in out  # 建议行未产出

    def test_error_text_fallback_chain(self):
        """历史单数 error 键信封经 errorText 链可达（不再渲染 undefined）。"""
        out = json.loads(_kit_call(
            "kit.kitApiErrorHtml({ ok: false, error: 'legacy' }, { hint: '' })"))
        assert "legacy" in out


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestShowApiErrorAndBusyNode:
    def test_show_api_error_guard_no_document(self):
        """node 裸环境：无 into 无 document → toast 回退缺席静默，返回 null。"""
        out = json.loads(_kit_call(
            "kit.showApiError({ ok: false, errors: ['x'] }, { title: 'T' })"))
        assert out is None

    def test_kit_btn_busy_three_states(self):
        """busy=disabled+aria-busy+spinner 文案；restore 还原原钮面；幂等。"""
        out = json.loads(_kit_call(
            "(() => { const b = { disabled: false, innerHTML: '<b>开始</b>',"
            " dataset: {}, setAttribute(n, v) { this['a_' + n] = v; },"
            " removeAttribute(n) { delete this['a_' + n]; } };"
            " kit.kitBtnBusy(b, true);"
            " const busy = { dis: b.disabled, busy: b.getAttribute"
            " ? null : b['a_aria-busy'], html: b.innerHTML,"
            " marked: b.dataset.kitIdleHtml != null };"
            " kit.kitBtnBusy(b, true); kit.kitBtnBusy(b, false);"  # 幂等 restore
            " const idle = { dis: b.disabled, html: b.innerHTML,"
            " marked: b.dataset.kitIdleHtml != null,"
            " aria: b['a_aria-busy'] == null };"
            " return { busy, idle, defaultLabel:"
            " b.innerHTML.indexOf('运行中') >= 0 ? 'kept' : busy.html }; })()"))
        assert out["busy"]["dis"] is True
        assert out["busy"]["busy"] == "true"
        assert "spin" in out["busy"]["html"]
        assert "运行中…" in out["busy"]["html"]  # 缺省钮面=common.busy zh
        assert out["busy"]["marked"] is True
        assert out["idle"]["dis"] is False
        assert out["idle"]["html"] == "<b>开始</b>"
        assert out["idle"]["marked"] is False
        assert out["idle"]["aria"] is True

    def test_kit_btn_busy_custom_label_and_silent_guards(self):
        """页域标签覆盖（import.reading 族）；非元素/无 disabled 静默。"""
        out = json.loads(_kit_call(
            "(() => { const b = { disabled: false, innerHTML: '读取工程',"
            " dataset: {}, setAttribute() {}, removeAttribute() {} };"
            " kit.kitBtnBusy(b, true, '读取中...（首次启动 AEDT 需 ~30s）');"
            " const custom = b.innerHTML;"
            " kit.kitBtnBusy(null, true); kit.kitBtnBusy({}, true);"
            " kit.kitBtnBusy({ disabled: 'x' }, true);"  # 静默不抛
            " return custom; })()"))
        assert "读取中..." in out and "spin" in out


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestApiErrorOptInNode:
    """api.js 开关双闸矩阵（fetch 桩；api.js 零 pages/ 依赖可裸 import）。"""

    _BOOT = (
        "const A = (c, m) => { if (!c) throw new Error('assert: ' + m); };\n"
        "const api = await import('./pages/api.js');\n"
        "const seen = [];\n"
        "api.setApiErrorPresenter((env, o) => seen.push([env.errors, o]));\n"
        "globalThis.fetch = async () =>"
        " ({ json: async () => ({ ok: false, errors: ['boom'] }) });\n")

    def test_opt_in_matrix(self):
        out = _run_node_js(self._BOOT +
            "await api.apiFetch('/a');\n"                                    # 缺省零行为
            "await api.apiFetch('/b', { apiError: true });\n"                # 布尔
            "await api.apiFetch('/c', { apiError: { title: 'T' } });\n"      # 对象透传
            "await api.apiFetch('/d', { apiError: false });\n"               # 显式关
            "A(seen.length === 2, '缺省/显式关不触发，flag 触发两次');\n"
            "A(JSON.stringify(seen[0]) === JSON.stringify([['boom'], {}]),"
            " '布尔形态透传空参');\n"
            "A(seen[1][1].title === 'T', '对象形态透传');\n"
            "console.log('ok:optin');\n")
        assert "ok:optin" in out

    def test_presenter_throw_swallowed_envelope_intact(self):
        out = _run_node_js(self._BOOT +
            "api.setApiErrorPresenter(() => { throw new Error('presenter boom'); });\n"
            "const d = await api.apiFetch('/e', { apiError: true });\n"
            "A(d.ok === false && d.errors[0] === 'boom', '信封原样返回');\n"
            "api.setApiErrorPresenter(null);\n"
            "const n = seen.length;\n"
            "await api.apiFetch('/f', { apiError: true });\n"
            "A(seen.length === n, '未注册 no-op');\n"
            "console.log('ok:swallow');\n")
        assert "ok:swallow" in out

    def test_aborted_envelope_not_presented(self):
        out = _run_node_js(self._BOOT +
            "globalThis.fetch = async (u, init) => new Promise((_, rej) =>\n"
            "  init.signal.addEventListener('abort', () =>\n"
            "    rej(Object.assign(new Error('a'), { name: 'AbortError' }))));\n"
            "const ac = new AbortController();\n"
            "const p = api.apiFetch('/g', { signal: ac.signal, apiError: true });\n"
            "ac.abort();\n"
            "const d = await p;\n"
            "A(d.aborted === true && seen.length === 0, '取消不进错误卡');\n"
            "console.log('ok:aborted');\n")
        assert "ok:aborted" in out

    def test_kit_registration_wiring(self):
        """kit.js 装配注册：同进程两模块 import 后 flag 即生效（呈现异常吞掉
        ——node 无 document 走 toast 回退缺席静默，信封照常返回）。"""
        out = _run_node_js(
            "const A = (c, m) => { if (!c) throw new Error('assert: ' + m); };\n"
            "const kit = await import('./pages/kit.js');\n"
            "const api = await import('./pages/api.js');\n"
            "globalThis.fetch = async () =>"
            " ({ json: async () => ({ ok: false, errors: ['x'] }) });\n"
            "const d = await api.apiFetch('/h', { apiError: true });\n"
            "A(d.ok === false, 'kit 注册后 flag 生效且不炸');\n"
            "A(typeof kit.showApiError === 'function', '导出在位');\n"
            "console.log('ok:kitreg');\n")
        assert "ok:kitreg" in out


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestR4I18nKeysNode:
    def test_new_keys_bilingual(self):
        """R4 增量键 zh/en 双语齐全（append-only；值零 HTML）。"""
        keys = [
            "common.error_title", "common.error_generic", "common.error_hint",
            "common.busy",
            "runs.empty_no_runs", "runs.goto_tune",
            "datasets.empty_none", "datasets.empty_none_next",
            "datasets.goto_guide", "datasets.clear_filter",
            "anchors.empty", "uq.goto_calibration",
            "import.save_confirm_title", "import.save_confirm_body_pre",
            "import.save_confirm_body_tail",
        ]
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const keys = " + json.dumps(keys) + ";\n"
            "const errs = [];\n"
            "for (const k of keys) {\n"
            "  const e = m.LOCALES[k];\n"
            "  if (!e || typeof e.zh !== 'string' || !e.zh) errs.push('zh: ' + k);\n"
            "  if (!e || typeof e.en !== 'string' || !e.en) errs.push('en: ' + k);\n"
            "}\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:r4keys:' + keys.length);\n")
        assert "ok:r4keys:15" in out


# ────────────────────── 2. 源码钉（免 node） ──────────────────────

class TestR4SourcePins:
    def test_kit_single_source_exports(self):
        for sig in ("export function kitApiErrorHtml(",
                    "export function showApiError(",
                    "export function kitBtnBusy("):
            assert sig in _KIT, sig
            assert _KIT.count(sig) == 1, sig + " 唯一性"
        # api.js 开关与注册面（api.js 保持零 pages/ 依赖——只存函数引用）
        assert "export function setApiErrorPresenter(" in _API
        assert "o.apiError" in _API and "_errorPresenter" in _API
        # kit.js 装配注册（缺省呈现通道；api.js 自身不 import kit——零环）
        assert "setApiErrorPresenter(" in _KIT
        assert "from \"./api.js\"" in _KIT

    def test_busy_wiring_sites(self):
        """长操作按钮 busy 接线四点（本席页面；tune/gallery 他席不在域）。"""
        assert "kitBtnBusy(btn, true);" in _DATA          # uq-run
        assert "kitBtnBusy(btn, true);" in _PROFILE       # pf-run
        assert "kitBtnBusy(btn, true, t(\"import.reading\"))" in _IMPORT  # imp-read
        assert "kitBtnBusy(btn, true); // R4" in _IMPORT  # imp-save
        # 旧手写形态不回潮
        assert 'btn.disabled = true; T.$("uq-spin")' not in _DATA
        assert 'btn.disabled = true; btn.textContent' not in _IMPORT
        assert 'T.$("uq-spin")' not in _DATA  # 独立 spin span 退役

    def test_unified_error_card_wiring(self):
        """错误呈现归一接线：view_data 四点 + view_import 两点走卡/单源。"""
        assert "showApiError(" in _DATA and "kitApiErrorHtml(" in _DATA
        assert "showApiError(" in _IMPORT
        # 裸读单数 error 键渲染 undefined 的病灶不回潮（filebrowser 实证）
        assert "esc(importSpec.error)" not in _IMPORT
        assert "errorText(r)" not in _IMPORT  # toast 拼接形态被错误卡取代

    def test_empty_states_three_piece(self):
        """空态三件式：runs 零记录引导/datasets 空库与筛选动作化/
        anchors 空注册表/uq 跳转钮；solvers 空表出缺省空态行。"""
        assert 't("runs.empty_no_runs")' in _RUNS
        assert '{ icon: "☰", label: t("runs.goto_tune"), view: "tune" }' in _RUNS
        assert 'bindEmptyStates(tb)' in _RUNS
        assert 't("datasets.empty_none")' in _DATA
        assert 'id: "ds-empty-clear"' in _DATA  # 筛选清除动作钮（runs 同款）
        assert 't("anchors.empty")' in _DATA
        assert '{ icon: "◔", label: t("uq.goto_calibration"), view: "calibration" }' in _DATA
        assert 'rows: d.solvers || [],\n      rowHtml:' in _SOLVERS  # empty:"" 退役

    def test_danger_confirm_wiring(self):
        """破坏性动作确认：保存草稿=kitConfirm 确认闸（onOk 后置执行）。"""
        assert "kitConfirm({" in _IMPORT
        assert 't("import.save_confirm_title")' in _IMPORT
        assert 't("import.save_confirm_body_pre")' in _IMPORT
        assert 't("import.save_confirm_body_tail")' in _IMPORT
        assert "onOk: () => doSaveRecipeDraft(outPath)" in _IMPORT
        # 原单击即发形态不回潮：onclick 直挂 doSave/旧 saveRecipeDraft 实体
        assert "T.$(\"imp-save\").onclick = saveRecipeDraft;" in _IMPORT
        assert "async function saveRecipeDraft" not in _IMPORT

    def test_api_flag_demo_site(self):
        """apiError 开关消费点（旧版忽略失败信封的 /api/recipe 尾段）。"""
        assert "apiError: { hint: t(\"common.error_hint\") }" in _IMPORT
        assert "if (rr.ok === false) return;" in _IMPORT


# ────────────────────── 3. 跨席钉保护（引用计数） ──────────────────────

class TestCrossSeatPinsIntact:
    def test_queue_error_form_exempt_site_untouched(self):
        """✗ 形态豁免点（queue）不动——余量恒 1（细钉在 test_ui_lifecycle）。"""
        q = (_STATIC / "pages" / "view_queue.js").read_text(encoding="utf-8")
        assert q.count("color:var(--err)'>✗") == 1

    def test_datasets_anchors_retry_sites_untouched(self):
        """既有 kitErrorPanel 重试接线（W14/a8 批）不在本批改动面。"""
        assert 'kitErrorPanel((d.errors || []).join("; "), "ds-retry")' in _DATA
        assert 'kitErrorPanel((d.errors || []).join("; "), "an-retry")' in _DATA

    def test_r12_unified_api_pins_kept(self):
        """统一 API 层形态钉保持：action-only 视图无 signal/无裸 fetch。"""
        assert "viewSignal(" not in _IMPORT
        assert "await fetch(" not in _IMPORT
        assert 'import { apiFetch } from "./api.js";' in _IMPORT
